"""Synchronisation dim_asset (référentiel CMDB complet) + KPI de couverture.

Le rapprochement asset <-> dim_node se fait par nom, au meilleur effort : un
CI iTop et un dim_node partagent rarement un identifiant direct (l'un a un
itop_ci_id de ticket, l'autre l'id interne d'un outil de monitoring), mais
partagent presque toujours un nom reconnaissable (même équipement, nommé de
façon cohérente par l'équipe qui l'a provisionné dans les deux systèmes).
Un rapprochement par IP serait plus fiable mais dim_asset ne porte pas
d'adresse IP — le CMDB de cette instance ne l'expose pas sur les classes
Server/NetworkDevice/PC utilisées ici (voir extract/itop.py::fetch_all_assets).
Affiner ce rapprochement (IP, numéro de série) est le premier endroit à
regarder si le taux de couverture calculé semble trop bas.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.dimension import Locality, Node
from app.schemas.assets import AssetSyncPayload

logger = logging.getLogger(__name__)


def sync_assets_bulk(db: Session, payloads: list[AssetSyncPayload]) -> dict[str, int]:
    if not payloads:
        return {"received": 0, "created": 0, "updated": 0, "matched_to_node": 0}

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    existing = {
        a.itop_ci_id: a
        for a in db.query(Asset).filter(
            Asset.itop_ci_id.in_({p.itop_ci_id for p in payloads})
        )
    }
    # Rapprochement par nom, insensible à la casse — voir docstring du module.
    node_by_name = {name.strip().lower(): node_id for name, node_id in db.query(Node.name, Node.id)}
    # Idem pour la localité : le nom de site iTop (location_name) est
    # rapproché du nom de dim_locality. Best-effort — si les libellés
    # divergent entre les deux systèmes (abréviations, orthographe), l'actif
    # est quand même créé, seulement sans locality_id, et ressort dans
    # aucune ligne de v_kpi_coverage_locality tant que ce n'est pas corrigé
    # (à la main ici, ou en alignant les libellés côté iTop).
    locality_by_name = {name.strip().lower(): loc_id for name, loc_id in db.query(Locality.name, Locality.id)}

    created = updated = matched = 0
    for p in payloads:
        node_id = node_by_name.get(p.name.strip().lower())
        if node_id is not None:
            matched += 1
        locality_id = (
            locality_by_name.get(p.location_name.strip().lower()) if p.location_name else None
        )

        asset = existing.get(p.itop_ci_id)
        if asset is None:
            asset = Asset(itop_ci_id=p.itop_ci_id)
            db.add(asset)
            created += 1
        else:
            updated += 1

        asset.name = p.name
        asset.asset_type = p.asset_type
        asset.is_monitored = node_id is not None
        asset.node_id = node_id
        asset.locality_id = locality_id
        asset.last_synced_at = now

    db.commit()
    return {
        "received": len(payloads),
        "created": created,
        "updated": updated,
        "matched_to_node": matched,
    }


def get_coverage_summary(db: Session) -> dict:
    rows = db.execute(
        text(
            "SELECT locality_id, locality, region_id, region, total_assets, "
            "monitored_assets, unmonitored_assets, coverage_pct "
            "FROM v_kpi_coverage_locality ORDER BY region, locality"
        )
    ).all()

    by_locality = [
        {
            "locality_id": r.locality_id,
            "locality": r.locality,
            "region_id": r.region_id,
            "region": r.region,
            "total_assets": r.total_assets,
            "monitored_assets": r.monitored_assets,
            "unmonitored_assets": r.unmonitored_assets,
            "coverage_pct": float(r.coverage_pct) if r.coverage_pct is not None else None,
        }
        for r in rows
    ]

    total = sum(r["total_assets"] for r in by_locality)
    monitored = sum(r["monitored_assets"] for r in by_locality)
    last_synced_at = db.execute(select(Asset.last_synced_at).order_by(Asset.last_synced_at.desc()).limit(1)).scalar()

    return {
        "total_assets": total,
        "monitored_assets": monitored,
        "unmonitored_assets": total - monitored,
        "coverage_pct": round(100.0 * monitored / total, 1) if total else None,
        "by_locality": by_locality,
        "last_synced_at": last_synced_at,
    }
