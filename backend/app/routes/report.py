"""Rapport mensuel d'exploitation."""
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import require_role
from app.models import User
from app.services import report_service

router = APIRouter(prefix="/api/report", tags=["rapports"])

_DOWNLOAD = ("directeur", "chef_noc")

_MEDIA_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@router.get("/monthly")
def download_monthly_report(
    month: int | None = Query(None, ge=1, le=12),
    year: int | None = Query(None, ge=2000, le=2100),
    format: str = Query("pdf", pattern="^(pdf|docx)$"),
    db: Session = Depends(get_db),
    _user: User = Depends(require_role(*_DOWNLOAD)),
):
    now = datetime.now(UTC)
    m, y = month or now.month, year or now.year

    try:
        path = report_service.generate(db, m, y, format)
    except Exception as exc:
        # Le frontend lit la réponse en blob et détecte le JSON d'erreur
        # (voir frontend/src/api/report.js) : renvoyer un détail lisible.
        raise HTTPException(
            status_code=500, detail=f"Le rapport n'a pas pu être généré : {exc}"
        ) from exc

    return FileResponse(
        path,
        media_type=_MEDIA_TYPES[format],
        filename=f"rapport-noc-{y}-{m:02d}.{format}",
    )
