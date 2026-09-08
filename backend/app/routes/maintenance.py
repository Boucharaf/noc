"""Fenêtres de maintenance planifiée."""
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_user, require_role
from app.models.operations import User
from app.schemas.maintenance import MaintenanceWindowCreate, MaintenanceWindowOut
from app.services import maintenance_service

router = APIRouter(prefix="/api/maintenance-windows", tags=["maintenance"])

_MANAGE = ("directeur", "chef_noc", "technicien")


@router.get("", response_model=list[MaintenanceWindowOut])
def list_windows(
    only_active: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return maintenance_service.list_windows(db, only_active, limit)


@router.post("", response_model=MaintenanceWindowOut, status_code=status.HTTP_201_CREATED)
def create_window(
    payload: MaintenanceWindowCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*_MANAGE)),
):
    return maintenance_service.create_window(
        db,
        user,
        node_id=payload.node_id,
        locality_id=payload.locality_id,
        reason=payload.reason,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        suppress_alerts=payload.suppress_alerts,
    )


@router.delete("/{window_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_window(
    window_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_role(*_MANAGE)),
):
    maintenance_service.delete_window(db, window_id)
