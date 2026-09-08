#!/usr/bin/env python3
"""
Jeu de données de démonstration pour l'entrepôt NOC.

À QUOI ÇA SERT : tant que les six connecteurs ne pointent pas vers les
vrais outils de l'agence, l'entrepôt est vide et tous les tableaux de bord
affichent « aucune donnée ». Impossible dans ces conditions de valider une
maquette, de former un exploitant ou de relire une revue d'écran. Ce
script écrit un parc plausible — géographie du Burkina Faso, six outils,
incidents étalés sur six mois, métriques TimescaleDB — pour que
l'interface soit jugeable sur pièces.

CE QU'IL RESPECTE VOLONTAIREMENT :

* les sévérités et statuts sont écrits BRUTS, dans le vocabulaire propre à
  chaque outil ('5' pour Zabbix, 'major' pour NSP, '2' pour Centreon…),
  exactement comme etl/transform/normalize_incidents.py les recopie. Semer
  des valeurs déjà normalisées donnerait une démo qui marche et une
  production qui ne marche pas, ce qui est pire que pas de démo du tout ;
* `source_tool` n'est jamais 'manual' : cette valeur est réservée aux
  signalements humains (incident_service.MANUAL_SOURCE_TOOL) ;
* rien n'est écrit dans les tables `ops_*` sauf les fenêtres de
  maintenance, pour que l'état « maintenance » de l'inventaire soit
  visible.

Usage :
    cd backend
    python scripts/seed_demo.py                # sème (idempotent)
    python scripts/seed_demo.py --purge        # efface ce qu'il a semé
    python scripts/seed_demo.py --nodes 120 --days 180

Les objets semés portent tous un marqueur reconnaissable
(external_id/external_ref préfixé par DEMO_PREFIX) : --purge n'efface donc
jamais de donnée réelle collectée par l'ETL.
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.core.config import WAREHOUSE_DSN  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402

DEMO_PREFIX = "demo-"

# --- Géographie -----------------------------------------------------------
REGIONS = [
    ("CEN", "Centre"),
    ("HBS", "Hauts-Bassins"),
    ("BMH", "Boucle du Mouhoun"),
    ("EST", "Est"),
    ("NRD", "Nord"),
    ("SAH", "Sahel"),
    ("CAS", "Cascades"),
    ("PCN", "Plateau-Central"),
]

# (localité, région, latitude, longitude)
LOCALITIES = [
    ("Ouagadougou", "CEN", 12.3714, -1.5197),
    ("Bobo-Dioulasso", "HBS", 11.1771, -4.2979),
    ("Koudougou", "CEN", 12.2530, -2.3622),
    ("Dédougou", "BMH", 12.4636, -3.4603),
    ("Fada N'Gourma", "EST", 12.0616, 0.3583),
    ("Ouahigouya", "NRD", 13.5828, -2.4216),
    ("Dori", "SAH", 14.0354, -0.0345),
    ("Banfora", "CAS", 10.6376, -4.7526),
    ("Ziniaré", "PCN", 12.5819, -1.2969),
    ("Tenkodogo", "CEN", 11.7800, -0.3697),
    ("Kaya", "CEN", 13.0917, -1.0839),
    ("Gaoua", "CAS", 10.3253, -3.1836),
]

MINISTRIES = [
    "Ministère de la Transition Digitale (MTDPCE)",
    "Ministère de l'Économie et des Finances",
    "Ministère de la Santé",
    "Ministère de l'Éducation Nationale",
    "Ministère de la Sécurité",
    "Ministère de l'Agriculture",
    "Présidence du Faso",
    "Primature",
]

NODE_TYPES = ["router", "switch", "firewall", "server", "link", "access_point"]

TOOLS = ["zabbix", "netxms", "centreon", "nagios", "itop", "nsp"]

# Vocabulaire BRUT par outil — voir noc_norm_severity() dans
# backend/sql/01_backend_extensions.sql pour la traduction.
RAW_SEVERITY = {
    "zabbix": ["1", "2", "3", "4", "5"],
    "netxms": ["1", "2", "3", "4"],
    "centreon": ["1", "2", "3"],
    "nagios": ["1", "2", "3"],
    "itop": ["1", "2", "3", "4"],
    "nsp": ["warning", "minor", "major", "critical"],
}
RAW_STATUS_OPEN = {
    "itop": ["new", "assigned", "pending"],
    "_default": ["open"],
}
RAW_STATUS_CLOSED = {
    "itop": ["resolved", "closed"],
    "_default": ["resolved"],
}

CAUSES = [
    "lien_down", "perte_paquets", "latence", "cpu", "memoire",
    "alimentation", "equipement_down", "seuil_trafic", "non_identifie",
]

DESCRIPTIONS = {
    "lien_down": "Interface {iface} hors service — perte de porteuse",
    "perte_paquets": "Perte de paquets {pct}% sur la liaison {iface}",
    "latence": "Latence {ms} ms au-dessus du seuil (100 ms)",
    "cpu": "Charge CPU soutenue à {pct}% pendant plus de 15 minutes",
    "memoire": "Occupation mémoire {pct}% — risque de swap",
    "alimentation": "Bascule sur onduleur — alimentation secteur absente",
    "equipement_down": "Équipement injoignable (ICMP timeout x5)",
    "seuil_trafic": "Trafic sortant {mb} Mb/s — seuil 80% de la capacité franchi",
    "non_identifie": "Anomalie détectée sans corrélation établie",
}

METRIC_TYPES = [
    "availability_pct", "latency_ms", "packet_loss_pct",
    "cpu_pct", "ram_pct", "bandwidth_in_mbps", "bandwidth_out_mbps",
]


def _describe(cause: str, rng: random.Random) -> str:
    return DESCRIPTIONS[cause].format(
        iface=f"Gi0/{rng.randint(0, 23)}",
        pct=rng.randint(82, 99),
        ms=rng.randint(120, 900),
        mb=rng.randint(80, 950),
    )


def purge(db) -> None:
    """Efface uniquement ce que ce script a semé.

    L'ordre suit les clés étrangères, des feuilles vers les racines. Le
    piège : `dim_node_source_map` est à la fois ce qui IDENTIFIE les
    équipements de démonstration et ce qui les RÉFÉRENCE. Il faut donc
    relever les identifiants AVANT de vider la table de correspondance,
    sinon on ne sait plus quels nœuds supprimer — et les supprimer
    d'abord viole `dim_node_source_map_node_id_fkey`.
    """
    print("Purge des données de démonstration…")
    prefix = {"p": f"{DEMO_PREFIX}%"}

    node_ids = [
        row[0]
        for row in db.execute(
            text("SELECT DISTINCT node_id FROM dim_node_source_map WHERE external_ref LIKE :p"),
            prefix,
        ).all()
    ]

    if node_ids:
        # Les tables ops_* liées à un incident sont en ON DELETE CASCADE :
        # supprimer fact_incident emporte sa chronologie, son affectation
        # et son marqueur de notification.
        db.execute(
            text("DELETE FROM metric_value WHERE node_id = ANY(:ids)"), {"ids": node_ids}
        )
        db.execute(
            text("DELETE FROM ops_field_intervention WHERE node_id = ANY(:ids)"),
            {"ids": node_ids},
        )
    db.execute(text("DELETE FROM fact_incident WHERE external_id LIKE :p"), prefix)
    db.execute(text("DELETE FROM ops_maintenance_window WHERE external_id LIKE :p"), prefix)
    db.execute(
        text(
            """
            DELETE FROM fact_supervision_coverage_daily
            WHERE locality_id IN (SELECT id FROM dim_locality WHERE external_ref LIKE :p)
               OR ministry_id IN (SELECT id FROM dim_ministry WHERE external_ref LIKE :p)
            """
        ),
        prefix,
    )
    db.execute(text("DELETE FROM dim_node_source_map WHERE external_ref LIKE :p"), prefix)
    if node_ids:
        db.execute(text("DELETE FROM dim_node WHERE id = ANY(:ids)"), {"ids": node_ids})
    db.execute(text("DELETE FROM dim_locality WHERE external_ref LIKE :p"), prefix)
    db.execute(text("DELETE FROM dim_ministry WHERE external_ref LIKE :p"), prefix)
    db.commit()
    print(f"Purge terminée ({len(node_ids)} équipements retirés).")


def seed_geography(db) -> tuple[dict, dict]:
    for code, name in REGIONS:
        db.execute(text("""
            INSERT INTO dim_region (code, name) VALUES (:code, :name)
            ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name
        """), {"code": code, "name": name})

    region_ids = {
        r[0]: r[1] for r in db.execute(text("SELECT code, id FROM dim_region")).all()
    }

    for name, region_code, lat, lon in LOCALITIES:
        db.execute(text("""
            INSERT INTO dim_locality (external_ref, region_id, code, name, latitude, longitude)
            VALUES (:ref, :region_id, :code, :name, :lat, :lon)
            ON CONFLICT (external_ref) DO UPDATE
              SET region_id = EXCLUDED.region_id, latitude = EXCLUDED.latitude,
                  longitude = EXCLUDED.longitude
        """), {
            "ref": f"{DEMO_PREFIX}loc-{name.lower().replace(' ', '-').replace(chr(39), '')}",
            "region_id": region_ids[region_code],
            "code": name[:3].upper(),
            "name": name, "lat": lat, "lon": lon,
        })

    for index, name in enumerate(MINISTRIES):
        db.execute(text("""
            INSERT INTO dim_ministry (external_ref, name) VALUES (:ref, :name)
            ON CONFLICT (external_ref) DO UPDATE SET name = EXCLUDED.name
        """), {"ref": f"{DEMO_PREFIX}min-{index}", "name": name})

    locality_ids = {
        r[0]: r[1] for r in db.execute(
            text("SELECT name, id FROM dim_locality WHERE external_ref LIKE :p"),
            {"p": f"{DEMO_PREFIX}%"},
        ).all()
    }
    ministry_ids = {
        r[0]: r[1] for r in db.execute(
            text("SELECT name, id FROM dim_ministry WHERE external_ref LIKE :p"),
            {"p": f"{DEMO_PREFIX}%"},
        ).all()
    }
    db.commit()
    print(f"Géographie : {len(REGIONS)} régions, {len(locality_ids)} sites, "
          f"{len(ministry_ids)} ministères.")
    return locality_ids, ministry_ids


def seed_nodes(db, locality_ids: dict, ministry_ids: dict, count: int,
               rng: random.Random) -> list[dict]:
    localities = list(locality_ids.items())
    ministries = list(ministry_ids.items())
    nodes: list[dict] = []

    for index in range(count):
        locality_name, locality_id = localities[index % len(localities)]
        ministry_name, ministry_id = rng.choice(ministries)
        node_type = rng.choice(NODE_TYPES)
        prefix = {"router": "RTR", "switch": "SW", "firewall": "FW",
                  "server": "SRV", "link": "LNK", "access_point": "AP"}[node_type]
        name = f"{prefix}-{locality_name[:3].upper()}-{index:03d}"
        ip = f"10.{rng.randint(10, 99)}.{rng.randint(0, 255)}.{rng.randint(2, 254)}"

        node_id = db.execute(text("""
            INSERT INTO dim_node (ministry_id, locality_id, name, ip_address, node_type, is_active)
            VALUES (:ministry_id, :locality_id, :name, :ip, :node_type, :is_active)
            ON CONFLICT (name, ip_address) DO UPDATE SET node_type = EXCLUDED.node_type
            RETURNING id
        """), {
            "ministry_id": ministry_id, "locality_id": locality_id, "name": name,
            "ip": ip, "node_type": node_type,
            # Quelques équipements inactifs : l'inventaire doit savoir les
            # distinguer d'un équipement muet.
            "is_active": rng.random() > 0.04,
        }).scalar()

        # Un équipement peut être vu par deux outils — c'est le cas réel
        # (Zabbix + Centreon sur le même routeur) et ce que
        # dim_node_source_map existe pour représenter.
        tools = rng.sample(TOOLS, k=rng.choice([1, 1, 1, 2, 2, 3]))
        for tool in tools:
            db.execute(text("""
                INSERT INTO dim_node_source_map (node_id, source_tool, external_ref)
                VALUES (:node_id, :tool, :ref)
                ON CONFLICT (source_tool, external_ref) DO NOTHING
            """), {"node_id": node_id, "tool": tool,
                   "ref": f"{DEMO_PREFIX}{tool}-{node_id}"})

        nodes.append({
            "id": node_id, "name": name, "tools": tools,
            "locality_id": locality_id, "locality": locality_name,
            "ministry": ministry_name, "type": node_type,
        })

    db.commit()
    print(f"Parc : {len(nodes)} équipements.")
    return nodes


def seed_incidents(db, nodes: list[dict], days: int, rng: random.Random) -> int:
    now = datetime.now(UTC)
    written = 0

    # Quelques équipements concentrent les pannes : c'est ce que le KPI
    # « équipements récurrents » et le Top 10 doivent faire ressortir. Une
    # distribution uniforme rendrait ces deux écrans vides de sens.
    hot_nodes = rng.sample(nodes, k=max(3, len(nodes) // 10))

    total = int(days * 2.2)
    for index in range(total):
        node = rng.choice(hot_nodes) if rng.random() < 0.35 else rng.choice(nodes)
        tool = rng.choice(node["tools"])
        cause = rng.choice(CAUSES)

        age_days = rng.random() * days
        detected = now - timedelta(days=age_days, minutes=rng.randint(0, 1439))

        # 70 % des incidents tombent en heures ouvrées : sans ce biais, la
        # distribution horaire est plate et le KPI « hors heures » ne dit
        # plus rien.
        if rng.random() < 0.7:
            detected = detected.replace(hour=rng.randint(7, 19))

        severity = rng.choice(RAW_SEVERITY[tool])
        still_open = age_days < 3 and rng.random() < 0.45

        if still_open:
            status = rng.choice(RAW_STATUS_OPEN.get(tool, RAW_STATUS_OPEN["_default"]))
            acknowledged = (
                detected + timedelta(minutes=rng.randint(3, 45))
                if rng.random() < 0.6 else None
            )
            resolved = None
            mttr = None
            downtime = None
        else:
            status = rng.choice(RAW_STATUS_CLOSED.get(tool, RAW_STATUS_CLOSED["_default"]))
            acknowledged = detected + timedelta(minutes=rng.randint(2, 60))
            resolved = acknowledged + timedelta(minutes=rng.randint(10, 700))
            mttr = round((resolved - detected).total_seconds() / 60, 1)
            downtime = round(mttr * rng.uniform(0.3, 1.0), 1)

        mtta = (
            round((acknowledged - detected).total_seconds() / 60, 1)
            if acknowledged else None
        )

        db.execute(text("""
            INSERT INTO fact_incident (
                source_tool, external_id, node_id, itop_ticket_ref, status, severity,
                cause_category, detected_at, acknowledged_at, resolved_at,
                mtta_minutes, mttr_minutes, downtime_minutes, description)
            VALUES (:tool, :ext, :node_id, :ticket, :status, :severity,
                    :cause, :detected, :ack, :resolved, :mtta, :mttr, :downtime, :description)
            ON CONFLICT (source_tool, external_id) DO NOTHING
        """), {
            "tool": tool,
            "ext": f"{DEMO_PREFIX}{tool}-inc-{index}",
            "node_id": node["id"],
            "ticket": f"R-{100000 + index}" if tool == "itop" else None,
            "status": status, "severity": severity, "cause": cause,
            "detected": detected, "ack": acknowledged, "resolved": resolved,
            "mtta": mtta, "mttr": mttr, "downtime": downtime,
            "description": _describe(cause, rng),
        })
        written += 1

    db.commit()
    print(f"Incidents : {written} lignes sur {days} jours.")
    return written


def seed_metrics(db, nodes: list[dict], days: int, rng: random.Random) -> int:
    """Métriques horaires.

    Volontairement horaires et non toutes les 5 minutes : sur 30 jours et
    100 équipements, un pas de 5 minutes ferait 8,6 millions de lignes
    pour une démo, sans rien montrer de plus à l'écran.
    """
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    hours = min(days, 30) * 24
    rows: list[dict] = []

    for node in nodes:
        tool = node["tools"][0]
        # Chaque équipement a son propre régime : sans cette base par
        # nœud, tous les classements « pires latences » sortent au hasard.
        base_latency = rng.uniform(8, 120)
        base_loss = rng.uniform(0, 3)
        base_cpu = rng.uniform(10, 70)
        base_ram = rng.uniform(25, 80)
        base_bw = rng.uniform(5, 400)
        flaky = rng.random() < 0.12

        for hour_offset in range(hours):
            ts = now - timedelta(hours=hour_offset)
            # Cycle jour/nuit sur le trafic et la charge.
            day_factor = 0.45 + 0.55 * (1 if 7 <= ts.hour <= 19 else 0.3)
            outage = flaky and rng.random() < 0.02

            values = {
                "availability_pct": 0.0 if outage else min(100.0, rng.gauss(99.6, 0.5)),
                "latency_ms": max(1.0, rng.gauss(base_latency * (1.8 if outage else 1.0), 6)),
                "packet_loss_pct": max(0.0, rng.gauss(base_loss * (6 if outage else 1.0), 0.6)),
                "cpu_pct": min(100.0, max(1.0, rng.gauss(base_cpu * day_factor * 1.4, 8))),
                "ram_pct": min(100.0, max(5.0, rng.gauss(base_ram, 4))),
                "bandwidth_in_mbps": max(0.0, rng.gauss(base_bw * day_factor, base_bw * 0.15)),
                "bandwidth_out_mbps": max(0.0, rng.gauss(base_bw * day_factor * 0.7, base_bw * 0.12)),
            }
            for metric_type, value in values.items():
                rows.append({
                    "time": ts, "node_id": node["id"], "tool": tool,
                    "metric_type": metric_type, "value": round(value, 3),
                })

        if len(rows) >= 20000:
            db.execute(text("""
                INSERT INTO metric_value (time, node_id, source_tool, metric_type, value)
                VALUES (:time, :node_id, :tool, :metric_type, :value)
            """), rows)
            db.commit()
            print(f"  … {len(rows)} points écrits")
            rows = []

    if rows:
        db.execute(text("""
            INSERT INTO metric_value (time, node_id, source_tool, metric_type, value)
            VALUES (:time, :node_id, :tool, :metric_type, :value)
        """), rows)
        db.commit()

    total = db.execute(text("SELECT count(*) FROM metric_value")).scalar()
    print(f"Métriques : {total} points au total dans metric_value.")
    return int(total or 0)


def seed_coverage(db, days: int, rng: random.Random) -> None:
    """Couverture de supervision quotidienne.

    L'ETL calcule cette table ; ici on la reconstitue à partir du parc
    semé pour que la page Supervision ait une tendance à afficher.
    """
    today = datetime.now(UTC).date()
    pairs = db.execute(text("""
        SELECT n.ministry_id, n.locality_id, count(*) AS total,
               count(*) FILTER (WHERE EXISTS (
                   SELECT 1 FROM dim_node_source_map s WHERE s.node_id = n.id
               )) AS supervised
        FROM dim_node n
        WHERE n.ministry_id IS NOT NULL AND n.locality_id IS NOT NULL
        GROUP BY n.ministry_id, n.locality_id
    """)).mappings().all()

    written = 0
    for day_offset in range(min(days, 90)):
        date = today - timedelta(days=day_offset)
        for row in pairs:
            # La couverture progresse doucement dans le temps : une courbe
            # plate ne permettrait pas de juger le graphe de tendance.
            drift = max(0, int(row["supervised"] * (day_offset / 400.0) * rng.uniform(0.5, 1.5)))
            db.execute(text("""
                INSERT INTO fact_supervision_coverage_daily
                    (date, ministry_id, locality_id, nb_equip_total, nb_equip_supervised)
                VALUES (:date, :ministry_id, :locality_id, :total, :supervised)
                ON CONFLICT (date, ministry_id, locality_id) DO UPDATE
                  SET nb_equip_total = EXCLUDED.nb_equip_total,
                      nb_equip_supervised = EXCLUDED.nb_equip_supervised
            """), {
                "date": date, "ministry_id": row["ministry_id"],
                "locality_id": row["locality_id"],
                "total": row["total"],
                "supervised": max(0, row["supervised"] - drift),
            })
            written += 1
    db.commit()
    print(f"Couverture : {written} lignes quotidiennes.")


def seed_maintenance(db, nodes: list[dict], rng: random.Random) -> None:
    now = datetime.now(UTC)
    windows = [
        # Une fenêtre en cours : rend l'état « maintenance » visible dans
        # l'inventaire dès l'ouverture de l'écran.
        (now - timedelta(hours=1), now + timedelta(hours=3), "Mise à jour firmware — lot 1"),
        (now + timedelta(days=2), now + timedelta(days=2, hours=4), "Bascule alimentation site"),
        (now - timedelta(days=6), now - timedelta(days=6) + timedelta(hours=5),
         "Remplacement carte optique"),
    ]
    for index, (starts, ends, reason) in enumerate(windows):
        node = rng.choice(nodes)
        # Le prédicat `WHERE source_tool IS NOT NULL` doit être répété :
        # idx_ops_maintenance_external est un index UNIQUE PARTIEL, et
        # PostgreSQL refuse de le retenir comme arbitre d'un ON CONFLICT
        # tant que la clause ne redit pas la même condition.
        db.execute(text("""
            INSERT INTO ops_maintenance_window
                (node_id, reason, starts_at, ends_at, suppress_alerts, source_tool, external_id)
            VALUES (:node_id, :reason, :starts, :ends, TRUE, 'demo', :ext)
            ON CONFLICT (source_tool, external_id) WHERE source_tool IS NOT NULL
            DO NOTHING
        """), {"node_id": node["id"], "reason": reason, "starts": starts,
               "ends": ends, "ext": f"{DEMO_PREFIX}mw-{index}"})
    db.commit()
    print(f"Maintenance : {len(windows)} fenêtres.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Jeu de données de démonstration NOC.")
    parser.add_argument("--nodes", type=int, default=60, help="Nombre d'équipements (défaut 60)")
    parser.add_argument("--days", type=int, default=180, help="Profondeur d'historique en jours")
    parser.add_argument("--purge", action="store_true", help="Efface les données de démo et sort")
    parser.add_argument("--seed", type=int, default=20260907, help="Graine aléatoire (reproductible)")
    args = parser.parse_args()

    print(f"Entrepôt : {WAREHOUSE_DSN.split('@')[-1]}")
    rng = random.Random(args.seed)
    db = SessionLocal()
    try:
        if args.purge:
            purge(db)
            return 0

        locality_ids, ministry_ids = seed_geography(db)
        nodes = seed_nodes(db, locality_ids, ministry_ids, args.nodes, rng)
        seed_incidents(db, nodes, args.days, rng)
        seed_metrics(db, nodes, args.days, rng)
        seed_coverage(db, args.days, rng)
        seed_maintenance(db, nodes, rng)

        print(
            "\nTerminé. Pensez à vider le cache KPI pour voir les chiffres tout de suite :\n"
            "  redis-cli --scan --pattern 'noc:*' | xargs -r redis-cli del\n"
            "…ou attendez l'expiration du cache (CACHE_TTL, 300 s par défaut)."
        )
        return 0
    except Exception as exc:  # pragma: no cover - outil d'exploitation
        db.rollback()
        print(f"Échec : {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
