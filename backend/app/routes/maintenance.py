from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.rate_limit import ingest_rate_limit, read_rate_limit
from app.core.security import get_current_user, require_role, verify_api_key
from app.db.session import get_db
from app.models.user import User
from app.schemas.maintenance import (
    MaintenanceWindowBulkImportPayload,
    MaintenanceWindowBulkImportResponse,
    MaintenanceWindowCreate,
    MaintenanceWindowOut,
)
from app.services import maintenance_service

router = APIRouter(prefix="/api/maintenance-windows", tags=["maintenance"])

# Déclarer une fenêtre de maintenance suppprime des alertes / masque des
# indisponibilités du SLA — même niveau d'habilitation que la résolution
# d'incident, pas l'acquittement.
_CREATE_ROLES = ("technicien", "chef_noc", "directeur")


@router.post(
    "",
    response_model=MaintenanceWindowOut,
    status_code=status.HTTP_201_CREATED,
)
def create_maintenance_window(
    payload: MaintenanceWindowCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*_CREATE_ROLES)),
):
    """Fenêtre de maintenance déclarée manuellement depuis le dashboard."""
    return maintenance_service.create_maintenance_window(db, payload, current_user.id)


@router.get(
    "",
    response_model=list[MaintenanceWindowOut],
    dependencies=[Depends(get_current_user), Depends(read_rate_limit)],
)
def list_maintenance_windows(db: Session = Depends(get_db)):
    return maintenance_service.list_active_windows(db)


@router.post(
    "/ingest/bulk",
    response_model=MaintenanceWindowBulkImportResponse,
)
def ingest_maintenance_windows_bulk(
    payload: MaintenanceWindowBulkImportPayload,
    db: Session = Depends(get_db),
    _: None = Depends(verify_api_key),
    __: None = Depends(ingest_rate_limit),
):
    """Import automatique des fenêtres actuellement actives dans chaque
    outil — voir etl/pipelines/tasks.collect_maintenance_windows."""
    return maintenance_service.ingest_maintenance_windows_bulk(db, payload.windows)
