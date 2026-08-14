"""
One-time CMDB backfill: create dim_node rows for the real infrastructure the
restored NetXMS instance supervises, so etl.extract.netxms.fetch_events has
something to match its alarms against.

Same problem as provision_itop_nodes.py, but with a much better source of
truth. The seeded demo dim_node data (fictional Burkina Faso government sites)
shares no names with the real NetXMS inventory — shelters, CPEs, liaisons PTP,
routeurs — so every alarm is skipped as unmatched and nothing is ingested.

Where the iTop backfill has to *guess* a locality from a name prefix, NetXMS
states it: each node carries a postal address (`postalAddress.city` /
`.region`) and a geolocation, filled in by the ANPTIC team. This script takes
the town from the data instead of inferring it, which is why it is allowed to
create localities the seed never had — it is transcribing a recorded fact, not
inventing geography.

The region strings are the messy part: the same region appears as
"CENTRE-EST", "Centre Est", "CENTE-EST"... and 324 nodes leave it blank
altogether. So the region is never read off a single node. Every node in a town
votes with whatever region name it carries, unrecognised spellings abstain, and
the town takes the majority — which is both typo-proof and fills in the blanks,
as long as one node in the town got it right.

Runs against the REST API rather than the NetXMS database, like every other
piece of the ETL. Note that GET /v1/objects returns only the root containers on
this instance (see the collector docstring), so the inventory is enumerated by
walking the tree with ?parent=<id>, descending through zones, subnets and
containers but never into a Node — a node's children are its 46 000 interfaces.

Dry run by default; pass --apply to write. Read the plan first: this inserts
~1400 nodes and the towns they sit in, and locality drives the geographic
breakdown of every KPI on the dashboard.

    docker compose exec etl-worker python provision_netxms_nodes.py
    docker compose exec etl-worker python provision_netxms_nodes.py --apply

Idempotent — skips any host whose name already exists in dim_node.
"""

import argparse
import logging
import re
import unicodedata
from collections import Counter, defaultdict

import psycopg2
import requests

import config
from extract.netxms import _as_list, _get, _login, _object_ip

# The "location not recorded" bucket is imported rather than redeclared: both
# backfills must land their unplaceable hosts in the same locality, or the
# dashboard grows two different "unknown" buckets that no reader can tell apart.
from provision_itop_nodes import (  # noqa: E402
    FALLBACK_LOCALITY_CODE,
    _ensure_fallback_locality,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# Container classes worth descending into. Node is deliberately absent: its
# children are interfaces, and there are 46 000 of them.
CONTAINER_CLASSES = {
    "Network",
    "Zone",
    "Subnet",
    "ServiceRoot",
    "Container",
    "Cluster",
    "Rack",
    "Chassis",
    "Collector",
}

# Normalized region string -> dim_region.code. The spellings here are the ones
# the restored instance actually contains, misspellings included: correcting
# "CENTE-EST" to Centre-Est is fixing a typo in an enumerated value, not
# guessing where a site is.
#
# Two values are deliberately unmapped. "FADA" is a town, not a region, and
# "GUIRIKO" belongs to the 2025 regional renaming, which dim_region does not
# use — mapping either would file nodes under a region nobody verified. They
# simply abstain from their town's vote, and the other nodes in the town decide.
REGION_ALIASES = {
    "CENTRE": "CEN",
    "KADIOGO": "CEN",  # province of Ouagadougou, région du Centre
    "CENTRE OUEST": "COU",
    "CENTRE EST": "CES",
    "CENTE EST": "CES",
    "CENRE EST": "CES",
    "CENTRE NORD": "CNO",
    "CENTER NORD": "CNO",
    "CENTRE SUD": "CSU",
    "NORD": "NOR",
    "EST": "EST",
    "REGION EST": "EST",
    "SUD OUEST": "SUO",
    "HAUT BASSIN": "HBS",
    "HAUTS BASSINS": "HBS",
    "HAUT BASSINT": "HBS",
    "PLATEAU CENTRAL": "PCE",
    "BOUCLE MOUHOUN": "BMH",
    "BOUCLE DU MOUHOUN": "BMH",
    "CASCADE": "CAS",
    "CASCADES": "CAS",
    "SAHEL": "SAH",
}

# Normalized city -> existing dim_locality.code, for towns the seed already
# holds under a fuller name. Without this, "FADA" would create a second
# locality alongside the seeded "Fada N'Gourma".
CITY_LOCALITY_ALIASES = {
    "FADA": "FAD",
}

# Towns whose region no node spells out. Fill one in — code from dim_region —
# once somebody confirms it, and the town is provisioned on the next run.
# Until then its nodes are reported and left out rather than filed under a
# region that was guessed.
CITY_REGION_OVERRIDES: dict[str, str] = {}

# (keyword, node_type) — first match on the upper-cased name wins, so the
# order matters: a PTP link between two shelters is a liaison, not a shelter,
# and "KAYA-SHELTER-RT02" is the shelter's router rather than a plain routeur.
NODE_TYPE_RULES = [
    ("PTP", "Liaison PTP"),
    ("P2P", "Liaison PTP"),
    ("SHELTER", "Shelter/Pylône"),
    ("PYLONE", "Shelter/Pylône"),
    ("CPE", "CPE / Routeur d'accès"),
    ("ONT", "ONT"),
    ("UBNT", "Point d'accès"),
    ("AP", "Point d'accès"),
    ("RT", "Routeur"),
    ("SW", "Switch"),
    ("FW", "Firewall"),
    ("SRV", "Serveur"),
    ("PC", "Poste de travail"),
]
DEFAULT_NODE_TYPE = "Infrastructure NetXMS"

NODE_CODE_PREFIX = "NXMS"


def _normalize(value: str) -> str:
    """Upper-case, accent- and punctuation-free form used for all matching."""
    decomposed = unicodedata.normalize("NFKD", value or "")
    unaccented = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9]+", " ", unaccented.upper()).strip()


def _title(value: str) -> str:
    """Display form for a town the seed does not already name."""
    return " ".join(part.capitalize() for part in value.split())


def _node_type(name: str) -> str:
    upper = name.upper()
    for keyword, node_type in NODE_TYPE_RULES:
        if keyword in upper:
            return node_type
    return DEFAULT_NODE_TYPE


def _walk_nodes(token: str) -> list[dict]:
    """Every Node object on the server, found by descending the object tree."""
    roots = _as_list(_get("/v1/objects", token), "objects")
    queue = [r.get("id") for r in roots if r.get("class") in CONTAINER_CLASSES]
    visited: set = set()
    nodes: dict = {}
    while queue:
        parent = queue.pop()
        if parent in visited:
            continue
        visited.add(parent)
        try:
            children = _as_list(_get(f"/v1/objects?parent={parent}", token), "objects")
        except requests.RequestException as exc:
            logger.warning("Could not list children of object %s: %s", parent, exc)
            continue
        for child in children:
            klass, oid = child.get("class"), child.get("id")
            if klass == "Node":
                nodes.setdefault(oid, child)
            elif klass in CONTAINER_CLASSES and oid not in visited:
                queue.append(oid)
    logger.info(
        "Walked %d containers, found %d Node objects", len(visited), len(nodes)
    )
    return list(nodes.values())


def _node_details(summaries: list[dict], token: str) -> list[dict]:
    """(name, ip, city, region) per node — the summaries from a ?parent= listing
    carry no postal address, so each node is fetched once."""
    details = []
    for summary in summaries:
        oid = summary.get("id")
        try:
            obj = _get(f"/v1/objects/{oid}", token)
        except requests.RequestException as exc:
            logger.warning("Could not read object %s: %s", oid, exc)
            continue
        if not isinstance(obj, dict):
            continue
        name = (obj.get("name") or "").strip()
        if not name:
            continue
        address = obj.get("postalAddress") or {}
        details.append(
            {
                "name": name,
                "ip": _object_ip(obj) or None,
                "city": _normalize(address.get("city") or ""),
                "region": _normalize(address.get("region") or ""),
            }
        )
    return details


def _resolve_town_regions(details: list[dict]) -> tuple[dict[str, str], list[str]]:
    """(town -> dim_region.code, towns left unresolved).

    One vote per node, unrecognised region spellings abstaining.
    """
    votes: dict[str, Counter] = defaultdict(Counter)
    for node in details:
        if not node["city"]:
            continue
        code = REGION_ALIASES.get(node["region"])
        if code:
            votes[node["city"]][code] += 1

    resolved, unresolved = {}, []
    for town in {n["city"] for n in details if n["city"]}:
        override = CITY_REGION_OVERRIDES.get(town)
        if override:
            resolved[town] = override
        elif votes[town]:
            resolved[town] = votes[town].most_common(1)[0][0]
        else:
            unresolved.append(town)
    return resolved, sorted(unresolved)


def _locality_code(town: str, taken: set[str]) -> str:
    """A free dim_locality.code (VARCHAR(10)) derived from the town name."""
    letters = re.sub(r"[^A-Z0-9]", "", town) or "LOC"
    for size in range(min(3, len(letters)), min(len(letters), 10) + 1):
        candidate = letters[:size]
        if candidate not in taken:
            return candidate
    for suffix in range(1, 1000):
        candidate = f"{letters[:6]}{suffix}"
        if candidate not in taken:
            return candidate
    raise RuntimeError(f"No free dim_locality code for {town!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write to the database (default: report the plan and change nothing)",
    )
    args = parser.parse_args()

    token = _login()
    details = _node_details(_walk_nodes(token), token)
    logger.info("Nodes with a usable name: %d", len(details))

    town_regions, unresolved_towns = _resolve_town_regions(details)
    logger.info("Towns named by the inventory: %d", len(town_regions))

    conn = psycopg2.connect(config.build_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT code, id FROM dim_region")
            region_ids = dict(cur.fetchall())

            cur.execute("SELECT id, code, name FROM dim_locality")
            locality_rows = cur.fetchall()
            locality_ids = {code: lid for lid, code, _ in locality_rows}
            locality_by_town = {_normalize(name): code for _, code, name in locality_rows}
            locality_by_town.update(CITY_LOCALITY_ALIASES)
            taken_codes = set(locality_ids)

            # Needed before any insert: a third of the inventory records no city
            # at all (central infrastructure, hosts named after an IP), and
            # those nodes are real regardless of where they sit.
            _ensure_fallback_locality(cur, locality_ids)
            taken_codes.add(FALLBACK_LOCALITY_CODE)

            cur.execute("SELECT lower(name) FROM dim_node")
            existing_names = {row[0] for row in cur.fetchall()}

            cur.execute(
                "SELECT code FROM dim_node WHERE code LIKE %s ORDER BY code DESC LIMIT 1",
                (f"{NODE_CODE_PREFIX}-%",),
            )
            row = cur.fetchone()
            next_seq = int(row[0].split("-")[1]) + 1 if row else 1

            # ── localities ──────────────────────────────────────────────
            created_localities = []
            for town, region_code in sorted(town_regions.items()):
                if town in locality_by_town:
                    continue
                region_id = region_ids.get(region_code)
                if region_id is None:
                    logger.warning(
                        "Town %s maps to region %s, which dim_region does not have"
                        " — skipping the town",
                        town,
                        region_code,
                    )
                    continue
                code = _locality_code(town, taken_codes)
                taken_codes.add(code)
                created_localities.append((code, town, region_code))
                if args.apply:
                    cur.execute(
                        "INSERT INTO dim_locality (region_id, code, name)"
                        " VALUES (%s, %s, %s) RETURNING id",
                        (region_id, code, _title(town)),
                    )
                    locality_ids[code] = cur.fetchone()[0]
                locality_by_town[town] = code

            # ── nodes ───────────────────────────────────────────────────
            inserted = skipped = no_town = 0
            by_locality: Counter = Counter()
            by_type: Counter = Counter()

            for node in sorted(details, key=lambda n: n["name"]):
                name = node["name"]
                if name.lower() in existing_names:
                    skipped += 1
                    continue
                # No city recorded is a different case from a city whose region
                # nobody could resolve: the first is honestly unknown and goes
                # to the fallback, the second names a real town and is held
                # back until CITY_REGION_OVERRIDES places it.
                if not node["city"]:
                    locality_code = FALLBACK_LOCALITY_CODE
                else:
                    locality_code = locality_by_town.get(node["city"])
                    if locality_code is None:
                        no_town += 1
                        continue

                node_type = _node_type(name)
                code = f"{NODE_CODE_PREFIX}-{next_seq:04d}"
                next_seq += 1
                if args.apply:
                    cur.execute(
                        "INSERT INTO dim_node"
                        " (locality_id, code, name, node_type, ip_address,"
                        "  source_tool, itop_ci_id, is_active)"
                        " VALUES (%s, %s, %s, %s, %s, 'netxms', NULL, TRUE)",
                        (
                            locality_ids[locality_code],
                            code,
                            name,
                            node_type,
                            node["ip"],
                        ),
                    )
                existing_names.add(name.lower())
                inserted += 1
                by_locality[locality_code] += 1
                by_type[node_type] += 1

        if args.apply:
            conn.commit()
        else:
            conn.rollback()
    finally:
        conn.close()

    verb = "Inserted" if args.apply else "Would insert"
    logger.info("")
    logger.info("%s localities: %d", verb, len(created_localities))
    for code, town, region_code in created_localities:
        logger.info("  %-10s %-24s region %s", code, _title(town), region_code)
    logger.info("%s nodes: %d (already present: %d)", verb, inserted, skipped)
    logger.info("By node_type: %s", dict(by_type.most_common()))
    logger.info("Top localities: %s", dict(by_locality.most_common(10)))
    if no_town:
        logger.warning(
            "Left out: %d node(s) sitting in one of the unresolved towns below",
            no_town,
        )
    if unresolved_towns:
        logger.warning(
            "Towns with no recognisable region on any node: %s."
            " Add them to CITY_REGION_OVERRIDES once confirmed.",
            ", ".join(unresolved_towns),
        )
    if not args.apply:
        logger.info("")
        logger.info("Dry run — nothing written. Re-run with --apply to commit.")


if __name__ == "__main__":
    main()
