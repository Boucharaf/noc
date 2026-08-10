"""
Replace the seeded demo dimensions with the real ANPTIC reference data, and
drop the demo facts that hang off them.

database/generate_seed.py invented ~150 nodes ("CHU Ouagadougou",
"Brigade Ouagadougou" on a 10.0.x.x plan) and six months of fact_incident rows
so the KPI endpoints had something to draw. The restored NetXMS instance
carries the real thing, so the demo data is now just noise sitting next to it
in the same tables and charts.

What the real data is, and where each piece comes from:

  dim_region    donnebase.limiteregion — the 2025 regional reform, 17 regions.
                Named with the new name and its predecessor ("Bankui
                (ex-Boucle du Mouhoun)") because the reform is recent, every
                NetXMS node address still spells the old name, and a reader
                looking for "Boucle du Mouhoun" has to be able to find it.
  dim_locality  donnebase.ville — the towns that actually host a node.
  dim_node      Placed by the real chain
                object_properties.siteadmin_id → siteadministratif → ville →
                commune → province → région, which resolves for every node
                that has a site link. Nodes without one fall back to matching
                their postal city against a ville name.
  dim_cause     transform.causes.TAXONOMY — see that module for why the seeded
                root-cause vocabulary could never be populated.

Nodes whose location the inventory does not record keep the existing
"Siège / infrastructure centrale" fallback, attached to Kadiogo.

Deletes: every dim_node the backfills did not create, and the fact_incident
rows referencing them. Those two sets coincide exactly — seeded incidents
only ever point at seeded nodes — so nothing real is caught by it. Demo user
accounts are left alone: dropping "admin" locks you out of the dashboard.

Dry run by default; --apply to write, in one transaction.

    docker compose exec etl-worker python rebuild_geography.py
    docker compose exec etl-worker python rebuild_geography.py --apply
"""

import argparse
import logging
import re
import unicodedata

import psycopg2

import config
from transform.causes import TAXONOMY, classify

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# Nodes the backfill scripts created; everything else in dim_node is seed data.
REAL_NODE_CODE_PREFIXES = ("NXMS-", "ITOP-")

FALLBACK_LOCALITY_CODE = "SIE"
FALLBACK_LOCALITY_NAME = "Siège / infrastructure centrale"
# Kadiogo (ex-Centre) — the region holding Ouagadougou, where the central
# infrastructure these nodes belong to actually sits.
FALLBACK_REGION_NEW_NAME = "KADIOGO"

# The centroid is what dim_locality.latitude/longitude feed: the dashboard map
# plots one marker per locality and silently drops any row without coordinates,
# so a locality with no lat/lon is a locality that does not exist on the map.
# donnebase geometry is SRID 4326 already, so the centroid is usable as-is.
GEO_QUERY = """
SELECT v.id_ville, v.nomville, r."Nouveau" AS region_new, r.nomregion AS region_old,
       ST_Y(ST_Centroid(v.geom))::numeric(9,6) AS latitude,
       ST_X(ST_Centroid(v.geom))::numeric(9,6) AS longitude
FROM donnebase.ville v
JOIN donnebase.limitecommune c  ON c.id_lcommune  = v.id_commune
JOIN donnebase.limiteprovince p ON p.id_lprovince = c.id_lprovince
JOIN donnebase.limiteregion r   ON r.id_lregion   = p.id_lregion
"""

# Node -> ville, by the site link when there is one. is_deleted=0 keeps the
# NetXMS recycle bin out of it.
NODE_SITE_QUERY = """
SELECT op.name, sa.id_ville, op.city
FROM nodes n
JOIN object_properties op ON op.object_id = n.id
LEFT JOIN donnebase.siteadministratif sa ON sa.id_siteadministratif = op.siteadmin_id
WHERE op.is_deleted = 0
"""


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    unaccented = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9]+", " ", unaccented.upper()).strip()


# French particles that stay lower-case inside a name ("Boucle du Mouhoun"),
# unless they open it.
_PARTICLES = {"du", "de", "des", "la", "le", "les", "d", "et"}


def _title(value: str) -> str:
    """Title-case a SHOUTED reference name.

    The source tables are upper-case throughout ("BOUCLE DU MOUHOUN",
    "BOBO-DIOULASSO"), and str.title/capitalize get both halves of this wrong:
    they lower-case the second element of a hyphenated name (Bobo-dioulasso)
    and capitalise particles (Boucle Du Mouhoun).
    """
    parts = re.split(r"([\s\-/]+)", value.strip().lower())
    out = []
    first = True
    for part in parts:
        if not part or re.fullmatch(r"[\s\-/]+", part):
            out.append(part)
            continue
        if part in _PARTICLES and not first:
            out.append(part)
        else:
            # Uppercase the first *letter*, not the first character, so a
            # parenthesised name ("(koupèla)") is capitalised too.
            out.append(re.sub(r"\w", lambda m: m.group().upper(), part, count=1))
        first = False
    return "".join(out)


def _short_code(name: str, taken: set[str], max_len: int = 10) -> str:
    letters = re.sub(r"[^A-Z0-9]", "", _normalize(name)) or "X"
    for size in range(min(3, len(letters)), min(len(letters), max_len) + 1):
        if letters[:size] not in taken:
            return letters[:size]
    for suffix in range(1, 1000):
        candidate = f"{letters[:max_len - len(str(suffix))]}{suffix}"
        if candidate not in taken:
            return candidate
    raise RuntimeError(f"No free code for {name!r}")


def _read_netxms() -> tuple[list[tuple], list[tuple]]:
    conn = psycopg2.connect(config.netxms_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(GEO_QUERY)
            geo = cur.fetchall()
            cur.execute(NODE_SITE_QUERY)
            nodes = cur.fetchall()
    finally:
        conn.close()
    return geo, nodes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write to the database")
    args = parser.parse_args()

    geo_rows, node_rows = _read_netxms()
    # id_ville -> (ville name, new region name); plus a name index for the
    # nodes that have no site link and can only be matched on their city.
    ville_by_id = {vid: (name, new, lat, lon) for vid, name, new, _, lat, lon in geo_rows}
    ville_by_name = {_normalize(name): vid for vid, name, *_ in geo_rows}
    regions = sorted({(new, old) for _, _, new, old, _, _ in geo_rows})
    logger.info("Reference data: %d régions, %d villes", len(regions), len(ville_by_id))

    # Resolve every NetXMS node to a ville id (or None -> fallback locality).
    placement: dict[str, int | None] = {}
    via_site = via_city = unplaced = 0
    for name, id_ville, city in node_rows:
        if id_ville in ville_by_id:
            placement[name] = id_ville
            via_site += 1
            continue
        matched = ville_by_name.get(_normalize(city or ""))
        if matched is not None:
            placement[name] = matched
            via_city += 1
        else:
            placement[name] = None
            unplaced += 1
    logger.info(
        "Nodes placed: %d by site link, %d by city name, %d to the fallback locality",
        via_site,
        via_city,
        unplaced,
    )

    conn = psycopg2.connect(config.build_dsn())
    try:
        with conn.cursor() as cur:
            # ── 1. drop the demo facts and nodes ────────────────────────
            like = " AND ".join(["code NOT LIKE %s"] * len(REAL_NODE_CODE_PREFIXES))
            params = tuple(f"{p}%" for p in REAL_NODE_CODE_PREFIXES)
            cur.execute(
                f"DELETE FROM fact_incident WHERE node_id IN"
                f" (SELECT id FROM dim_node WHERE {like})",
                params,
            )
            deleted_incidents = cur.rowcount
            cur.execute(f"DELETE FROM dim_node WHERE {like}", params)
            deleted_nodes = cur.rowcount

            # The seeded rows are deleted at step 5, but their codes are needed
            # now: "SAB" is both a demo locality and a real ville, and the
            # surviving nodes still reference the old rows so they cannot be
            # dropped before the repoint. Park them on throwaway codes instead,
            # which frees every real code for its rightful owner.
            cur.execute("UPDATE dim_locality SET code = '#' || id")
            cur.execute("UPDATE dim_region SET code = '#' || id")

            # ── 2. real regions ─────────────────────────────────────────
            region_ids: dict[str, int] = {}
            region_codes: set[str] = set()
            for new_name, old_name in regions:
                code = _short_code(new_name, region_codes)
                region_codes.add(code)
                cur.execute(
                    "INSERT INTO dim_region (code, name) VALUES (%s, %s) RETURNING id",
                    (code, f"{_title(new_name)} (ex-{_title(old_name)})"),
                )
                region_ids[new_name] = cur.fetchone()[0]

            # ── 3. real localities, only where a node actually sits ─────
            used_villes = {v for v in placement.values() if v is not None}
            locality_ids: dict[int | None, int] = {}
            locality_codes: set[str] = set()
            for id_ville in sorted(used_villes):
                ville_name, region_new, latitude, longitude = ville_by_id[id_ville]
                code = _short_code(ville_name, locality_codes)
                locality_codes.add(code)
                cur.execute(
                    "INSERT INTO dim_locality (region_id, code, name, latitude, longitude)"
                    " VALUES (%s, %s, %s, %s, %s) RETURNING id",
                    (
                        region_ids[region_new],
                        code,
                        _title(ville_name),
                        latitude,
                        longitude,
                    ),
                )
                locality_ids[id_ville] = cur.fetchone()[0]

            # Deliberately without coordinates: it is not a place. The map drops
            # rows with no lat/lon, which is the right outcome — pinning "location
            # not recorded" onto Ouagadougou would read as 163 nodes genuinely
            # sited there. It still appears in every non-map locality list.
            locality_codes.add(FALLBACK_LOCALITY_CODE)
            cur.execute(
                "INSERT INTO dim_locality (region_id, code, name)"
                " VALUES (%s, %s, %s) RETURNING id",
                (
                    region_ids[FALLBACK_REGION_NEW_NAME],
                    FALLBACK_LOCALITY_CODE,
                    FALLBACK_LOCALITY_NAME,
                ),
            )
            locality_ids[None] = cur.fetchone()[0]

            # ── 4. repoint the surviving nodes ──────────────────────────
            cur.execute("SELECT id, name FROM dim_node")
            remapped = to_fallback = stranded = 0
            for node_id, node_name in cur.fetchall():
                if node_name not in placement:
                    # An iTop-provisioned host, or a NetXMS node deleted since
                    # the backfill: no location to look up, park it on the
                    # fallback rather than leave a dangling locality_id.
                    target = locality_ids[None]
                    stranded += 1
                elif placement[node_name] is None:
                    target = locality_ids[None]
                    to_fallback += 1
                else:
                    target = locality_ids[placement[node_name]]
                    remapped += 1
                cur.execute(
                    "UPDATE dim_node SET locality_id = %s WHERE id = %s",
                    (target, node_id),
                )

            # ── 5. old dimensions, now unreferenced ─────────────────────
            cur.execute(
                "DELETE FROM dim_locality WHERE id <> ALL(%s)",
                (list(locality_ids.values()),),
            )
            dropped_localities = cur.rowcount
            cur.execute(
                "DELETE FROM dim_region WHERE id <> ALL(%s)",
                (list(region_ids.values()),),
            )
            dropped_regions = cur.rowcount

            # ── 6. real cause taxonomy, and backfill what was collected ─
            # Detach before deleting: the live collector has already been
            # creating cause rows of its own through get_or_create_cause, so
            # the table is not simply the 13 seeded ones. Everything is
            # reclassified from the taxonomy below anyway.
            cur.execute("UPDATE fact_incident SET cause_id = NULL WHERE cause_id IS NOT NULL")
            cur.execute("DELETE FROM dim_cause")
            dropped_causes = cur.rowcount
            cause_ids: dict[tuple[str, str], int] = {}
            for category, label in TAXONOMY:
                cur.execute(
                    "INSERT INTO dim_cause (category, label) VALUES (%s, %s) RETURNING id",
                    (category, label),
                )
                cause_ids[(category, label)] = cur.fetchone()[0]

            cur.execute("SELECT id, description FROM fact_incident")
            classified = 0
            for incident_id, description in cur.fetchall():
                key = classify(description)
                cause_id = cause_ids.get(key)
                if cause_id is None:
                    continue
                cur.execute(
                    "UPDATE fact_incident SET cause_id = %s WHERE id = %s",
                    (cause_id, incident_id),
                )
                classified += 1

            cur.execute("REFRESH MATERIALIZED VIEW mv_kpi_node_monthly")

        if args.apply:
            conn.commit()
        else:
            conn.rollback()
    finally:
        conn.close()

    prefix = "" if args.apply else "[dry run] "
    logger.info("")
    logger.info("%sDemo data removed: %d incident(s), %d node(s)", prefix, deleted_incidents, deleted_nodes)
    logger.info("%sRégions:   %d real, %d seeded dropped", prefix, len(region_ids), dropped_regions)
    logger.info(
        "%sLocalités: %d real villes + %s, %d seeded dropped",
        prefix, len(locality_ids) - 1, FALLBACK_LOCALITY_CODE, dropped_localities,
    )
    logger.info(
        "%s  %d node(s) placed in their ville, %d on %s (%d with no location recorded,"
        " %d not in the NetXMS inventory)",
        prefix, remapped, to_fallback + stranded, FALLBACK_LOCALITY_CODE, to_fallback, stranded,
    )
    logger.info("%sCauses:    %d real, %d seeded dropped", prefix, len(cause_ids), dropped_causes)
    logger.info("%s  %d incident(s) classified onto a cause", prefix, classified)
    if not args.apply:
        logger.info("")
        logger.info("Dry run — nothing written. Re-run with --apply to commit.")


if __name__ == "__main__":
    main()
