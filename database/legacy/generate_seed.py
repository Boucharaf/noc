#!/usr/bin/env python3
"""
Generates database/02_seed.sql — demo data for the NOC/ANPTIC dashboard.

Produces the 13 administrative regions of Burkina Faso, a spread of localities
and ~150 supervised nodes (matching the cahier des charges' "150+ nœuds"), a
cause dimension, and 6 months of realistic fact_incident rows so every KPI
endpoint (summary, trend, recurrent nodes, hour distribution, SLA, alerts...)
has something meaningful to show out of the box.

Re-run this script whenever the demo dataset needs to be regenerated:
    python3 database/generate_seed.py
It is deterministic (fixed random seed) so the output is stable across runs.
"""

import hashlib
import random
from datetime import datetime, timedelta, timezone

random.seed(42)

OUT_PATH = "database/02_seed.sql"

# ---------------------------------------------------------------------------
# Dimensions
# ---------------------------------------------------------------------------

REGIONS = [
    ("BMH", "Boucle du Mouhoun"),
    ("CAS", "Cascades"),
    ("CEN", "Centre"),
    ("CES", "Centre-Est"),
    ("CNO", "Centre-Nord"),
    ("COU", "Centre-Ouest"),
    ("CSU", "Centre-Sud"),
    ("EST", "Est"),
    ("HBS", "Hauts-Bassins"),
    ("NOR", "Nord"),
    ("PCE", "Plateau-Central"),
    ("SAH", "Sahel"),
    ("SUO", "Sud-Ouest"),
]

# code, name, region_code, lat, lon, population
LOCALITIES = [
    ("DED", "Dédougou", "BMH", 12.4600, -3.4600, 58000),
    ("BAN", "Banfora", "CAS", 10.6333, -4.7667, 110000),
    ("OUA", "Ouagadougou", "CEN", 12.3714, -1.5197, 2800000),
    ("TEN", "Tenkodogo", "CES", 11.7800, -0.3700, 44000),
    ("KAY", "Kaya", "CNO", 13.0917, -1.0844, 74000),
    ("KOU", "Koudougou", "COU", 12.2530, -2.3620, 120000),
    ("PO", "Pô", "CSU", 11.1717, -1.1450, 24000),
    ("FAD", "Fada N'Gourma", "EST", 12.0617, 0.3547, 65000),
    ("BOB", "Bobo-Dioulasso", "HBS", 11.1771, -4.2979, 970000),
    ("OUH", "Ouahigouya", "NOR", 13.5828, -2.4214, 115000),
    ("ZIN", "Ziniaré", "PCE", 12.5817, -1.2972, 28000),
    ("DOR", "Dori", "SAH", 14.0350, -0.0350, 46000),
    ("GAO", "Gaoua", "SUO", 10.3333, -3.1833, 34000),
    ("OUN", "Ouagadougou (Zone Nord)", "CEN", 12.4200, -1.5000, 350000),
]

NODE_TYPES = ["Administratif", "Santé", "Financier", "Éducatif", "Sécurité"]
SOURCE_TOOLS = ["zabbix", "nagios", "netxms", "centreon"]

CAUSES = [
    ("Énergie", "Délestage / onduleur sans reprise auto"),
    ("Énergie", "Groupe électrogène en panne"),
    ("Énergie", "Batterie onduleur déchargée"),
    ("Équipement", "Panne routeur"),
    ("Équipement", "Panne switch"),
    ("Équipement", "Surchauffe matérielle"),
    ("Liaison", "Coupure fibre optique"),
    ("Liaison", "Latence réseau élevée"),
    ("Liaison", "Perte de signal VSAT"),
    ("Logiciel", "Service applicatif indisponible"),
    ("Logiciel", "Erreur de configuration"),
    ("Humain", "Intervention non planifiée"),
    ("Humain", "Coupure accidentelle de câble"),
]

FACILITY_NAMES = {
    "Administratif": [
        "Gouvernorat",
        "Préfecture",
        "Mairie",
        "DREP",
        "Haut-Commissariat",
    ],
    "Santé": ["Hôpital Régional", "CHU", "CSPS", "District Sanitaire"],
    "Financier": ["Trésor Public", "Perception", "Douanes"],
    "Éducatif": ["Direction Régionale Éducation", "Lycée Public", "Université"],
    "Sécurité": ["Commissariat", "Gendarmerie", "Brigade"],
}

NODES_PER_LOCALITY = {
    "OUA": 30,
    "BOB": 20,
    "OUN": 12,
    "DED": 9,
    "BAN": 9,
    "TEN": 9,
    "KAY": 9,
    "KOU": 9,
    "PO": 8,
    "FAD": 9,
    "OUH": 9,
    "ZIN": 8,
    "DOR": 8,
    "GAO": 8,
}
# -> totals ~157 nodes, matching the "150+ nœuds" from the cahier des charges.

MONTHS_OF_HISTORY = 6


def sql_escape(value):
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, datetime):
        return f"'{value.strftime('%Y-%m-%d %H:%M:%S')}'"
    return "'" + str(value).replace("'", "''") + "'"


def insert_stmt(table, columns, rows):
    if not rows:
        return ""
    lines = [f"INSERT INTO {table} ({', '.join(columns)}) VALUES"]
    value_lines = []
    for row in rows:
        value_lines.append("  (" + ", ".join(sql_escape(v) for v in row) + ")")
    lines.append(",\n".join(value_lines) + ";")
    return "\n".join(lines)


def month_bounds(dt_ref: datetime, offset: int):
    """Return (start, end_exclusive) for dt_ref's month shifted back by `offset` months."""
    total = dt_ref.year * 12 + (dt_ref.month - 1) - offset
    year, month0 = divmod(total, 12)
    month = month0 + 1
    start = datetime(year, month, 1)
    end_total = total + 1
    end_year, end_month0 = divmod(end_total, 12)
    end = datetime(end_year, end_month0 + 1, 1)
    return start, end


def main():
    out = []
    out.append(
        "-- Auto-generated demo dataset. Regenerate with: python3 database/generate_seed.py"
    )
    out.append("-- Do not hand-edit; edit generate_seed.py instead.\n")

    # --- dim_region ---
    region_id_by_code = {}
    region_rows = []
    for i, (code, name) in enumerate(REGIONS, start=1):
        region_id_by_code[code] = i
        region_rows.append((i, code, name))
    out.append(insert_stmt("dim_region", ["id", "code", "name"], region_rows))
    out.append(f"SELECT setval('dim_region_id_seq', {len(region_rows)});")

    # --- dim_locality ---
    locality_id_by_code = {}
    locality_rows = []
    for i, (code, name, region_code, lat, lon, pop) in enumerate(LOCALITIES, start=1):
        locality_id_by_code[code] = i
        locality_rows.append(
            (i, region_id_by_code[region_code], code, name, lat, lon, pop)
        )
    out.append(
        insert_stmt(
            "dim_locality",
            ["id", "region_id", "code", "name", "latitude", "longitude", "population"],
            locality_rows,
        )
    )
    out.append(f"SELECT setval('dim_locality_id_seq', {len(locality_rows)});")

    # --- dim_cause ---
    cause_id_by_pair = {}
    cause_rows = []
    for i, (category, label) in enumerate(CAUSES, start=1):
        cause_id_by_pair[(category, label)] = i
        cause_rows.append((i, category, label))
    out.append(insert_stmt("dim_cause", ["id", "category", "label"], cause_rows))
    out.append(f"SELECT setval('dim_cause_id_seq', {len(cause_rows)});")

    # --- dim_node ---
    node_rows = []
    node_ids = []  # (id, code, locality_code)
    node_id = 0
    for locality_code, count in NODES_PER_LOCALITY.items():
        for seq in range(1, count + 1):
            node_id += 1
            node_type = NODE_TYPES[(node_id + seq) % len(NODE_TYPES)]
            facility = random.choice(FACILITY_NAMES[node_type])
            _, locality_name, *_ = next(
                loc for loc in LOCALITIES if loc[0] == locality_code
            )
            code = f"{locality_code}-{seq:03d}"
            name = f"{facility} {locality_name}"
            source_tool = SOURCE_TOOLS[node_id % len(SOURCE_TOOLS)]
            ip_address = (
                f"10.{(node_id // 254) % 254}.{node_id % 254}.{(node_id * 7) % 254 + 1}"
            )
            itop_ci_id = f"CI-{node_id:05d}"
            is_active = random.random() > 0.03
            node_rows.append(
                (
                    node_id,
                    locality_id_by_code[locality_code],
                    code,
                    name,
                    node_type,
                    ip_address,
                    source_tool,
                    itop_ci_id,
                    is_active,
                )
            )
            node_ids.append((node_id, code, locality_code))
    out.append(
        insert_stmt(
            "dim_node",
            [
                "id",
                "locality_id",
                "code",
                "name",
                "node_type",
                "ip_address",
                "source_tool",
                "itop_ci_id",
                "is_active",
            ],
            node_rows,
        )
    )
    out.append(f"SELECT setval('dim_node_id_seq', {len(node_rows)});")

    # --- fact_incident ---
    # Pick ~15 nodes to be "recurrent offenders" so /kpi/recurrent has real signal.
    recurrent_nodes = set(
        random.sample([n[0] for n in node_ids], k=min(15, len(node_ids)))
    )

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    incident_rows = []
    incident_id = 0
    itop_seq = 0

    for month_offset in range(MONTHS_OF_HISTORY - 1, -1, -1):
        start, end = month_bounds(now, month_offset)
        is_current_month = month_offset == 0
        span_seconds = (
            int((min(end, now) - start).total_seconds())
            if is_current_month
            else int((end - start).total_seconds())
        )
        span_seconds = max(span_seconds, 3600)

        for node_id_val, code, locality_code in node_ids:
            base_count = (
                6
                if node_id_val in recurrent_nodes
                else random.choices([0, 1, 2, 3], weights=[35, 35, 20, 10])[0]
            )
            n_incidents = base_count if node_id_val in recurrent_nodes else base_count
            if node_id_val in recurrent_nodes:
                n_incidents = random.randint(4, 9)

            for _ in range(n_incidents):
                incident_id += 1
                offset_seconds = random.randint(0, span_seconds - 1)
                detected_at = start + timedelta(seconds=offset_seconds)

                severity = random.choices(
                    ["critical", "high", "medium", "low"], weights=[15, 25, 40, 20]
                )[0]

                if is_current_month:
                    status = random.choices(
                        ["open", "acknowledged", "resolved", "closed"],
                        weights=[25, 20, 35, 20],
                    )[0]
                elif month_offset == 1:
                    # Previous month: a handful of incidents can still be genuinely open.
                    status = random.choices(
                        ["resolved", "closed", "acknowledged", "open"],
                        weights=[50, 40, 7, 3],
                    )[0]
                else:
                    # Older months: fully triaged, nothing realistically stays open this long.
                    status = random.choices(["resolved", "closed"], weights=[55, 45])[0]

                acknowledged_at = None
                resolved_at = None
                downtime_minutes = 0
                if status in ("acknowledged", "resolved", "closed"):
                    acknowledged_at = detected_at + timedelta(
                        minutes=random.randint(2, 45)
                    )
                if status in ("resolved", "closed"):
                    resolved_at = acknowledged_at + timedelta(
                        minutes=random.randint(10, 480)
                    )
                    downtime_minutes = int(
                        (resolved_at - detected_at).total_seconds() // 60
                    )
                elif status == "acknowledged":
                    downtime_minutes = (
                        int((now - detected_at).total_seconds() // 60)
                        if is_current_month
                        else 0
                    )

                category, label = random.choice(CAUSES)
                cause_id = cause_id_by_pair[(category, label)]

                source_tool = SOURCE_TOOLS[incident_id % len(SOURCE_TOOLS)]
                external_id = f"{source_tool}-alert-{incident_id:06d}"

                itop_ticket_id = None
                if random.random() > 0.15:
                    itop_seq += 1
                    itop_ticket_id = f"TKT-{detected_at.year}-{itop_seq:05d}"

                description = f"{label} — {code}"

                incident_rows.append(
                    (
                        incident_id,
                        node_id_val,
                        cause_id,
                        itop_ticket_id,
                        external_id,
                        status,
                        severity,
                        detected_at,
                        acknowledged_at,
                        resolved_at,
                        downtime_minutes,
                        source_tool,
                        description,
                    )
                )

    out.append(
        insert_stmt(
            "fact_incident",
            [
                "id",
                "node_id",
                "cause_id",
                "itop_ticket_id",
                "external_id",
                "status",
                "severity",
                "detected_at",
                "acknowledged_at",
                "resolved_at",
                "downtime_minutes",
                "source_tool",
                "description",
            ],
            incident_rows,
        )
    )
    out.append(f"SELECT setval('fact_incident_id_seq', {len(incident_rows)});")

    # --- dim_user (demo accounts) ---
    import bcrypt

    def bcrypt_hash(password):
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    def pin_hash(pin):
        return hashlib.sha256(pin.encode()).hexdigest()

    DEMO_USERS = [
        # username, full_name, role, password, pin
        ("admin", "Admin NOC", "admin", "admin123", "1234"),
        ("analyst", "Analyste ANPTIC", "analyst", "analyst123", "2222"),
        ("noc_agent", "Agent NOC", "noc_agent", "noc123", "3333"),
#1) directeur: ("admin", "Admin NOC", "directeur", "admin123", "1234"),
#2)chef noc: ("chefnoc", "Chef NOC", "chef_noc", "chef1234", "2222"),
#3) technicien("noc_technicien", "Technicien NOC", "technicien", "tech123", "3333"),
#4) agent_terrain: ("noc_agent", "Agent NOC", "agent_terrain", "noc123", "4444")

    ]
    user_rows = [
        (i, username, full_name, role, bcrypt_hash(password), pin_hash(pin))
        for i, (username, full_name, role, password, pin) in enumerate(
            DEMO_USERS, start=1
        )
    ]
    out.append(
        insert_stmt(
            "dim_user",
            ["id", "username", "full_name", "role", "password_hash", "pin_hash"],
            user_rows,
        )
    )
    out.append(f"SELECT setval('dim_user_id_seq', {len(user_rows)});")

    out.append("\nREFRESH MATERIALIZED VIEW mv_kpi_node_monthly;")

    with open(OUT_PATH, "w") as f:
        f.write("\n\n".join(part for part in out if part) + "\n")

    print(
        f"Wrote {OUT_PATH}: {len(region_rows)} regions, {len(locality_rows)} localities, "
        f"{len(node_rows)} nodes, {len(cause_rows)} causes, {len(incident_rows)} incidents."
    )


if __name__ == "__main__":
    main()
