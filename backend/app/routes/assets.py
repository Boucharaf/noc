from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.rate_limit import ingest_rate_limit, read_rate_limit
from app.core.security import get_current_user, verify_api_key
from app.db.session import get_db
from app.schemas.assets import AssetBulkSyncPayload, AssetBulkSyncResponse, CoverageSummaryOut
from app.services import asset_service, cache_service

router = APIRouter(prefix="/api/assets", tags=["assets"])


@router.post("/sync/bulk", response_model=AssetBulkSyncResponse)
def sync_assets_bulk(
    payload: AssetBulkSyncPayload,
    db: Session = Depends(get_db),
    _: None = Depends(verify_api_key),
    __: None = Depends(ingest_rate_limit),
):
    """Synchronisation quotidienne du parc CMDB complet — voir
    etl/pipelines/tasks.sync_asset_inventory. Un appel remplace l'état connu
    de chaque actif (upsert sur itop_ci_id), il ne supprime jamais un actif
    absent du lot : un CI temporairement invisible côté iTop ne doit pas
    disparaître du référentiel de couverture."""
    result = asset_service.sync_assets_bulk(db, payload.assets)
    if result["created"] or result["updated"]:
        cache_service.invalidate_prefix("kpi:")
    return result


@router.get(
    "/coverage",
    response_model=CoverageSummaryOut,
    dependencies=[Depends(get_current_user), Depends(read_rate_limit)],
)
def get_coverage(db: Session = Depends(get_db)):
    """Taux de couverture de supervision, global et par site — le KPI que
    dim_node seul ne permettait pas de calculer (voir l'audit du schéma :
    dim_node ne contient que ce que les outils remontent déjà)."""
    return asset_service.get_coverage_summary(db)
