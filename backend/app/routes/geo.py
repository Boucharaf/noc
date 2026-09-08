"""
Référentiel géographique.

Alimente les listes déroulantes de filtre (ministère / région / site) et
le formulaire de création de compte, où le périmètre d'un utilisateur est
un identifiant de région, de site ou de ministère.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.rate_limit import read_rate_limit
from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.operations import User
from app.schemas.geo import LocalityOut, MinistryOut, ReferenceOut, RegionOut
from app.services import geo_service

router = APIRouter(
    prefix="/api/geo",
    tags=["référentiel"],
    dependencies=[Depends(read_rate_limit)],
)


@router.get("/reference", response_model=ReferenceOut)
def get_reference(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    """Tout le référentiel en un appel — voir geo_service.get_reference."""
    return geo_service.get_reference(db)


@router.get("/regions", response_model=list[RegionOut])
def list_regions(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return geo_service.list_regions(db)


@router.get("/localities", response_model=list[LocalityOut])
def list_localities(
    region_id: int | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return geo_service.list_localities(db, region_id)


@router.get("/ministries", response_model=list[MinistryOut])
def list_ministries(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    return geo_service.list_ministries(db)
