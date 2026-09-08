"""
Taux de couverture de supervision.

Remplace l'ancien `asset_service` et sa table `dim_asset`, qui n'existent
plus : le nouvel ETL calcule lui-même la couverture dans
`fact_supervision_coverage_daily` (etl/load/load_facts.py::refresh_supervision_coverage,
tâche Celery planifiée à 02:00). Le backend n'a plus à synchroniser un
référentiel d'actifs depuis iTop, il lit le résultat.

Définition retenue par l'ETL, qu'il faut connaître pour interpréter le
chiffre : un équipement est « supervisé » dès qu'il a au moins une ligne
dans `dim_node_source_map`, c'est-à-dire dès qu'un outil au moins le
remonte. Comme `dim_node` n'est peuplée QUE par ce que les outils
renvoient, le total et le nombre supervisé sont aujourd'hui identiques :
le taux vaudra 100 % tant qu'aucune source de parc « théorique »
(inventaire iTop complet) n'alimente dim_node. C'est une limite du
périmètre actuel, pas un bug — elle est signalée dans la réponse par
`is_complete_inventory`.
"""
from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _pct(supervised: int, total: int) -> float | None:
    return round(supervised / total * 100, 1) if total else None


def get_coverage(db: Session, as_of: date | None = None) -> dict:
    """Couverture globale et par site, au dernier jour calculé."""
    last_date = db.execute(
        text(
            """
            SELECT max(date) FROM fact_supervision_coverage_daily
            WHERE (CAST(:as_of AS DATE) IS NULL OR date <= :as_of)
            """
        ),
        {"as_of": as_of},
    ).scalar()

    if last_date is None:
        # La tâche nocturne n'a jamais tourné : on calcule à la volée
        # plutôt que de renvoyer une page vide. Même définition que
        # l'ETL, pour que les deux chiffres restent comparables.
        return _live_coverage(db)

    rows = db.execute(
        text(
            """
            SELECT
                c.locality_id,
                COALESCE(l.name, 'Site non rattaché') AS locality,
                l.region_id,
                COALESCE(r.name, '—')                 AS region,
                c.ministry_id,
                COALESCE(m.name, '—')                 AS ministry,
                sum(c.nb_equip_total)      AS total_assets,
                sum(c.nb_equip_supervised) AS monitored_assets
            FROM fact_supervision_coverage_daily c
            LEFT JOIN dim_locality l ON l.id = c.locality_id
            LEFT JOIN dim_region   r ON r.id = l.region_id
            LEFT JOIN dim_ministry m ON m.id = c.ministry_id
            WHERE c.date = :as_of
            GROUP BY c.locality_id, l.name, l.region_id, r.name, c.ministry_id, m.name
            ORDER BY total_assets DESC
            """
        ),
        {"as_of": last_date},
    ).mappings().all()

    by_locality = []
    total = monitored = 0
    for r in rows:
        t, mo = int(r["total_assets"] or 0), int(r["monitored_assets"] or 0)
        total += t
        monitored += mo
        by_locality.append(
            {
                "locality_id": r["locality_id"],
                "locality": r["locality"],
                "region_id": r["region_id"],
                "region": r["region"],
                "ministry_id": r["ministry_id"],
                "ministry": r["ministry"],
                "total_assets": t,
                "monitored_assets": mo,
                "unmonitored_assets": t - mo,
                "coverage_pct": _pct(mo, t),
            }
        )

    return {
        "as_of": last_date,
        "source": "fact_supervision_coverage_daily",
        "is_complete_inventory": False,
        "total_assets": total,
        "monitored_assets": monitored,
        "unmonitored_assets": total - monitored,
        "coverage_pct": _pct(monitored, total),
        "by_locality": by_locality,
    }


def _live_coverage(db: Session) -> dict:
    rows = db.execute(
        text(
            """
            SELECT
                n.locality_id,
                COALESCE(l.name, 'Site non rattaché') AS locality,
                l.region_id,
                COALESCE(r.name, '—')                 AS region,
                n.ministry_id,
                COALESCE(m.name, '—')                 AS ministry,
                count(*) AS total_assets,
                count(*) FILTER (
                    WHERE EXISTS (SELECT 1 FROM dim_node_source_map s WHERE s.node_id = n.id)
                ) AS monitored_assets
            FROM dim_node n
            LEFT JOIN dim_locality l ON l.id = n.locality_id
            LEFT JOIN dim_region   r ON r.id = l.region_id
            LEFT JOIN dim_ministry m ON m.id = n.ministry_id
            GROUP BY n.locality_id, l.name, l.region_id, r.name, n.ministry_id, m.name
            ORDER BY total_assets DESC
            """
        )
    ).mappings().all()

    by_locality = []
    total = monitored = 0
    for r in rows:
        t, mo = int(r["total_assets"]), int(r["monitored_assets"])
        total += t
        monitored += mo
        by_locality.append(
            {
                "locality_id": r["locality_id"],
                "locality": r["locality"],
                "region_id": r["region_id"],
                "region": r["region"],
                "ministry_id": r["ministry_id"],
                "ministry": r["ministry"],
                "total_assets": t,
                "monitored_assets": mo,
                "unmonitored_assets": t - mo,
                "coverage_pct": _pct(mo, t),
            }
        )

    return {
        "as_of": date.today(),
        "source": "calcul direct (tâche nocturne jamais exécutée)",
        "is_complete_inventory": False,
        "total_assets": total,
        "monitored_assets": monitored,
        "unmonitored_assets": total - monitored,
        "coverage_pct": _pct(monitored, total),
        "by_locality": by_locality,
    }


def get_coverage_trend(db: Session, days: int = 30) -> list[dict]:
    rows = db.execute(
        text(
            """
            SELECT date,
                   sum(nb_equip_total)      AS total_assets,
                   sum(nb_equip_supervised) AS monitored_assets
            FROM fact_supervision_coverage_daily
            WHERE date > current_date - CAST(:days AS INT)
            GROUP BY date
            ORDER BY date
            """
        ),
        {"days": max(1, days)},
    ).mappings().all()

    return [
        {
            "date": r["date"],
            "total_assets": int(r["total_assets"] or 0),
            "monitored_assets": int(r["monitored_assets"] or 0),
            "coverage_pct": _pct(int(r["monitored_assets"] or 0), int(r["total_assets"] or 0)),
        }
        for r in rows
    ]
