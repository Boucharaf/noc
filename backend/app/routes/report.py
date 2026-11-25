"""Rapport mensuel d'exploitation."""
import contextlib
import logging
import os
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.db.session import get_db
from app.dependencies.auth import require_internal_key, require_role
from app.models import User
from app.services import (
    audit_service,
    report_archive_service,
    report_service,
    weekly_report_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/report", tags=["rapports"])
internal_router = APIRouter(prefix="/api/internal", tags=["interne"])

_DOWNLOAD = ("directeur", "chef_noc")
_GENERATION_FAILED = (
    "Le rapport n'a pas pu être généré. La cause est consignée dans les journaux du backend."
)

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


@router.get("/weekly")
async def download_weekly_report(
    db: Session = Depends(get_db),
    _user: User = Depends(require_role(*_DOWNLOAD)),
):
    """Rapport des sept derniers jours (AM-27), le même que celui envoyé
    chaque semaine par courriel."""
    try:
        path = await weekly_report_service.generate(db)
    except Exception as exc:
        logger.exception("Rapport hebdomadaire : génération en échec")
        raise HTTPException(status_code=500, detail=_GENERATION_FAILED) from exc
    now = datetime.now(UTC)
    year, week, _day = now.isocalendar()
    # Fichier temporaire : supprimé une fois envoyé, sinon chaque
    # téléchargement laisserait un rapport complet dans /tmp.
    return FileResponse(
        path, media_type=_MEDIA_TYPES["pdf"], filename=f"rapport-noc-{year}-S{week:02d}.pdf",
        background=BackgroundTask(_remove_quietly, path),
    )


class FreezeIn(BaseModel):
    month: int = Field(ge=1, le=12)
    year: int = Field(ge=2000, le=2100)
    reason: str | None = Field(None, max_length=500)


@router.get("/archive")
def list_archive(
    db: Session = Depends(get_db),
    _user: User = Depends(require_role(*_DOWNLOAD)),
):
    """Rapports mensuels figés, du plus récent au plus ancien."""
    try:
        return report_archive_service.list_snapshots(db)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.warning("Archives illisibles : %s", exc)
        raise HTTPException(
            status_code=503, detail="Archives indisponibles : rejouer backend/sql/schema.sql."
        ) from exc


@router.post("/archive", status_code=201)
async def freeze_report(
    body: FreezeIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(*_DOWNLOAD)),
):
    """Fige le rapport d'un mois clos (nouvelle révision s'il l'est déjà)."""
    username = user.username
    try:
        result = await report_archive_service.freeze(
            db, body.year, body.month, by=username, reason=body.reason
        )
    except report_archive_service.NotFreezable as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        logger.exception("Rapport %02d/%d : figement en échec", body.month, body.year)
        raise HTTPException(status_code=500, detail=_GENERATION_FAILED) from exc
    audit_service.record(
        db, "report.frozen", actor=user,
        target=f"{body.year}-{body.month:02d} révision {result['revision']}",
        detail={"reason": result["reason"], "sha256": result["pdf_sha256"]}, request=request,
    )
    return result


@router.get("/archive/{snapshot_id}/{part}")
def download_archive(
    snapshot_id: int,
    part: Literal["pdf", "json"],
    db: Session = Depends(get_db),
    _user: User = Depends(require_role(*_DOWNLOAD)),
):
    try:
        found = report_archive_service.read(db, snapshot_id, part)
    except report_archive_service.Corrupted as exc:
        logger.error("Empreinte incorrecte : %s", exc)
        raise HTTPException(
            status_code=409,
            detail="Ce rapport ne correspond plus à son empreinte : il a été altéré.",
        ) from exc
    if found is None:
        raise HTTPException(status_code=404, detail="Rapport introuvable.")
    row, content = found
    name = f"rapport-noc-{row['year']}-{row['month']:02d}-r{row['revision']}.{part}"
    return Response(
        content,
        media_type="application/pdf" if part == "pdf" else "application/json",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


def _remove_quietly(path: str) -> None:
    with contextlib.suppress(OSError):
        os.remove(path)


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
