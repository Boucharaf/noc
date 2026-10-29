"""Rapport mensuel d'exploitation."""
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import require_internal_key, require_role
from app.models import User
from app.services import report_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/report", tags=["rapports"])
internal_router = APIRouter(prefix="/api/internal", tags=["interne"])

_DOWNLOAD = ("directeur", "chef_noc")

_MEDIA_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class InternalMonthlyReportIn(BaseModel):
    month: int | None = Field(None, ge=1, le=12)
    year: int | None = Field(None, ge=2000, le=2100)
    format: str = Field("pdf", pattern="^(pdf|docx)$")


@router.get("/monthly")
async def download_monthly_report(
    month: int | None = Query(None, ge=1, le=12),
    year: int | None = Query(None, ge=2000, le=2100),
    format: str = Query("pdf", pattern="^(pdf|docx)$"),
    db: Session = Depends(get_db),
    _user: User = Depends(require_role(*_DOWNLOAD)),
):
    now = datetime.now(UTC)
    m, y = month or now.month, year or now.year

    try:
        path = await report_service.generate(db, m, y, format)
    except Exception as exc:
        # La cause reste dans les journaux du backend. Le message d'une
        # exception (requête SQL, chemin du disque, nom d'hôte de la base)
        # n'a rien à faire dans une réponse HTTP.
        logger.exception("Rapport %s %02d/%d : génération en échec", format, m, y)
        # Le frontend lit la réponse en blob et détecte le JSON d'erreur
        # (voir frontend/src/lib/download.js) : renvoyer un détail lisible.
        raise HTTPException(
            status_code=500,
            detail="Le rapport n'a pas pu être généré. La cause est consignée dans les journaux du backend.",
        ) from exc

    return FileResponse(
        path,
        media_type=_MEDIA_TYPES[format],
        filename=f"rapport-noc-{y}-{m:02d}.{format}",
    )


@internal_router.post("/reports/monthly")
async def generate_internal_monthly_report(
    body: InternalMonthlyReportIn,
    db: Session = Depends(get_db),
    _internal: None = Depends(require_internal_key),
):
    now = datetime.now(UTC)
    month, year = body.month or now.month, body.year or now.year
    try:
        path = await report_service.generate(db, month, year, body.format)
    except Exception as exc:
        logger.exception(
            "Rapport interne %s %02d/%d : génération en échec",
            body.format,
            month,
            year,
        )
        raise HTTPException(
            status_code=500,
            detail="Le rapport n'a pas pu être généré.",
        ) from exc
    return FileResponse(
        path,
        media_type=_MEDIA_TYPES[body.format],
        filename=f"rapport-noc-{year}-{month:02d}.{body.format}",
    )
