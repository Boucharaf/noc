"""
Référentiel géographique et listes de valeurs.

Sert à peupler les filtres du dashboard (ministère / région / site /
type d'équipement / outil source) et le formulaire de création de compte.
Sans cet endpoint, le frontend devrait deviner les valeurs possibles ou
les coder en dur — ce qui casserait dès que l'ETL découvre une nouvelle
localité.

Toutes les tables lues ici sont peuplées par
etl/scripts/discover_geography.py. Tant qu'il n'a pas tourné, les listes
sont vides : ce n'est pas une erreur, et le frontend doit l'afficher
comme « aucune donnée géographique » plutôt que comme une panne.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import cache_service

CACHE_PREFIX = "noc:geo:"
# Le référentiel bouge au rythme des découvertes de l'ETL (quelques fois
# par jour au plus) : un cache plus long que celui des KPI est justifié.
CACHE_TTL_S = 600


def list_regions(db: Session) -> list[dict]:
    rows = db.execute(
        text(
            """
            SELECT r.id, r.code, r.name,
                   (SELECT count(*) FROM dim_locality l WHERE l.region_id = r.id) AS nb_localities,
                   (SELECT count(*) FROM dim_node n
                     JOIN dim_locality l2 ON l2.id = n.locality_id
                    WHERE l2.region_id = r.id AND n.is_active) AS nb_nodes
            FROM dim_region r
            ORDER BY r.name
            """
        )
    ).mappings().all()
    return [dict(r) for r in rows]


def list_localities(db: Session, region_id: int | None = None) -> list[dict]:
    rows = db.execute(
        text(
            """
            SELECT l.id, l.code, l.name,
                   l.region_id, r.name AS region,
                   l.latitude, l.longitude,
                   (SELECT count(*) FROM dim_node n
                     WHERE n.locality_id = l.id AND n.is_active) AS nb_nodes
            FROM dim_locality l
            LEFT JOIN dim_region r ON r.id = l.region_id
            WHERE (CAST(:region_id AS INT) IS NULL OR l.region_id = :region_id)
            ORDER BY l.name
            """
        ),
        {"region_id": region_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def list_ministries(db: Session) -> list[dict]:
    rows = db.execute(
        text(
            """
            SELECT m.id, m.name, m.external_ref,
                   (SELECT count(*) FROM dim_node n
                     WHERE n.ministry_id = m.id AND n.is_active) AS nb_nodes
            FROM dim_ministry m
            ORDER BY m.name
            """
        )
    ).mappings().all()
    return [dict(r) for r in rows]


def get_reference(db: Session) -> dict:
    """Tout le référentiel en un appel.

    Le frontend en a besoin au montage de chaque écran filtrable ; six
    requêtes séparées au chargement d'un dashboard, c'est six allers-retours
    pour de la donnée qui ne change pas d'une heure à l'autre.
    """
    cached = cache_service.get_cached(CACHE_PREFIX + "reference")
    if cached is not None:
        return cached

    node_types = [
        r[0]
        for r in db.execute(
            text(
                """
                SELECT DISTINCT node_type FROM dim_node
                WHERE node_type IS NOT NULL AND node_type <> ''
                ORDER BY node_type
                """
            )
        ).all()
    ]
    source_tools = [
        r[0]
        for r in db.execute(
            text("SELECT DISTINCT source_tool FROM dim_node_source_map ORDER BY source_tool")
        ).all()
    ]
    causes = [
        {"category": r[0], "label": r[1]}
        for r in db.execute(text("SELECT category, label FROM dim_cause ORDER BY label")).all()
    ]

    payload = {
        "regions": list_regions(db),
        "localities": list_localities(db),
        "ministries": list_ministries(db),
        "node_types": node_types,
        "source_tools": source_tools,
        "causes": causes,
    }
    cache_service.set_cached(CACHE_PREFIX + "reference", payload, ttl=CACHE_TTL_S)
    return payload
