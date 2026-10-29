"""Lecture du journal d'audit — Chef NOC et Directeur.

L'écriture n'a pas de route : chaque action sensible écrit sa ligne elle-même
(app/services/audit_service.py). Le journal ne se modifie ni ne se purge
depuis l'interface.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import require_role
from app.models import User
from app.services import audit_service

router = APIRouter(prefix="/api/audit", tags=["audit"])

# Miroir de PERMISSIONS.VIEW_AUDIT dans frontend/src/lib/permissions.js.
_VIEW_AUDIT = ("chef_noc", "directeur")


@router.get("")
def list_audit(
    action: str | None = Query(None, max_length=60),
    user_id: int | None = Query(None, ge=1),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _viewer: User = Depends(require_role(*_VIEW_AUDIT)),
):
    return audit_service.list_entries(db, action, user_id, limit, offset)
