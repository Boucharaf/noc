"""
One-time CMDB backfill: create dim_node rows for the real infrastructure
iTop's ticket stream actually references, so etl.extract.itop.fetch_events
has something to match against.

The seeded demo dim_node data (fictional Burkina Faso government sites) shares
no names with the real hosts in iTop tickets (network shelters, routers,
switches, hypervisors...) — nothing from iTop is ingested until matching rows
exist. This script mines the active ticket set for distinct host names using
the same extraction logic as the live collector, and inserts one dim_node per
host: a confidently-matched locality where the leading name segment maps to
an existing town, the new 'SIE' fallback locality otherwise; a node_type
guessed from naming keywords; the IP if the name embeds one.

Run once, manually: docker compose exec etl-worker python provision_itop_nodes.py
Idempotent — skips any host whose name already exists in dim_node.
"""

import logging
from collections import Counter

import psycopg2

import config
from extract.itop import _clean_host_hint, _HOST_DESCRIPTION_RE, _HOST_TITLE_RE, _query

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# Leading '-'-delimited token (uppercased) -> existing dim_locality.code.
# Confident matches only — see plan discussion for why the many other town
# prefixes seen in real ticket data (KOUP, DIAL, SABO, KONG, OROD, NAKO,
# DANO, TANG, KORS, KOMB, YAKO, GOUR, REO, NOBE, BOUS, ...) are left to fall
# back to SIE rather than guessing an unverified region.
LOCALITY_PREFIX_MAP = {
    "GAOU": "GAO",
    "GAOUA": "GAO",
    "BOBO": "BOB",
    "OUAG": "OUA",
    "OUA3": "OUA",
    "OUAHI": "OUH",
    "KAYA": "KAY",
    "DORI": "DOR",
    "TENKO": "TEN",
    "BANF": "BAN",
    "ZINI": "ZIN",
    "DED": "DED",
    "DEDOU": "DED",
    "FAD": "FAD",
    "FADA": "FAD",
    "KOU": "KOU",
    "KOUD": "KOU",
    "PO": "PO",
}
FALLBACK_LOCALITY_CODE = "SIE"

# (keyword, node_type) — first substring match (case-insensitive) wins.
NODE_TYPE_RULES = [
    ("SHELTER", "Shelter/Pylône"),
    ("BSR", "Shelter/Pylône"),
    ("BST", "Shelter/Pylône"),
    ("HBS", "Shelter/Pylône"),
    ("PTP", "Liaison PTP"),
    ("HYPERVISEUR", "Hyperviseur"),
    ("FW", "Firewall"),
    ("BACKUP", "Sauvegarde"),
    ("SRV", "Serveur"),
    ("SW", "Switch"),
    ("CPE", "Routeur"),
    ("RT", "Routeur"),
]
DEFAULT_NODE_TYPE = "Infrastructure iTop"


def _extract_hosts() -> tuple[dict[str, str | None], int]:
    """(name -> ip-or-None) for every distinct host referenced by an active
    ticket, plus the count of tickets with no extractable host hint."""
    data = _query(
        key="SELECT Incident WHERE operational_status NOT IN ('resolved', 'closed')",
        output_fields="ref,title,description,priority,start_date,functionalcis_list",
    )
    hosts: dict[str, str | None] = {}
    no_hint = 0
    for obj in (data.get("objects") or {}).values():
        fields = obj.get("fields", {})
        m = _HOST_DESCRIPTION_RE.search(fields.get("description") or "") or _HOST_TITLE_RE.search(
            fields.get("title") or ""
        )
        if not m:
            no_hint += 1
            continue
        name, ip = _clean_host_hint(m.group(1))
        if name and name not in hosts:
            hosts[name] = ip
    return hosts, no_hint


def _locality_id(name: str, locality_ids: dict[str, int]) -> int:
    prefix = name.split("-", 1)[0].upper()
    code = LOCALITY_PREFIX_MAP.get(prefix, FALLBACK_LOCALITY_CODE)
    return locality_ids[code]


def _node_type(name: str) -> str:
    upper = name.upper()
    for keyword, node_type in NODE_TYPE_RULES:
        if keyword in upper:
            return node_type
    return DEFAULT_NODE_TYPE


def main() -> None:
    hosts, no_hint = _extract_hosts()
    logger.info("Distinct hosts extracted from active tickets: %d", len(hosts))
    logger.info("Tickets with no extractable host hint: %d", no_hint)

    conn = psycopg2.connect(config.build_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT code, id FROM dim_locality")
            locality_ids = dict(cur.fetchall())

            cur.execute("SELECT lower(name) FROM dim_node")
            existing_names = {row[0] for row in cur.fetchall()}

            cur.execute(
                "SELECT code FROM dim_node WHERE code LIKE 'ITOP-%' ORDER BY code DESC LIMIT 1"
            )
            row = cur.fetchone()
            next_seq = int(row[0].split("-")[1]) + 1 if row else 1

            inserted = 0
            skipped = 0
            by_locality: Counter[str] = Counter()
            by_type: Counter[str] = Counter()

            for name, ip in hosts.items():
                if name.lower() in existing_names:
                    skipped += 1
                    continue

                locality_id = _locality_id(name, locality_ids)
                node_type = _node_type(name)
                code = f"ITOP-{next_seq:04d}"
                next_seq += 1

                cur.execute(
                    "INSERT INTO dim_node"
                    " (locality_id, code, name, node_type, ip_address, source_tool, itop_ci_id, is_active)"
                    " VALUES (%s, %s, %s, %s, %s, 'itop', NULL, TRUE)",
                    (locality_id, code, name, node_type, ip),
                )
                existing_names.add(name.lower())
                inserted += 1
                by_locality[locality_id] += 1
                by_type[node_type] += 1

        conn.commit()
    finally:
        conn.close()

    id_to_code = {v: k for k, v in locality_ids.items()}
    logger.info("Inserted: %d, skipped (already present): %d", inserted, skipped)
    logger.info("By locality: %s", {id_to_code[k]: v for k, v in by_locality.items()})
    logger.info("By node_type: %s", dict(by_type))


if __name__ == "__main__":
    main()
