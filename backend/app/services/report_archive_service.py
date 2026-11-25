"""
Rapports mensuels figés.

POURQUOI. Le rapport téléchargé est recalculé à chaque fois : un ticket iTop
modifié ou purgé, une journée recalculée, et le rapport d'un mois passé ne
rend plus les mêmes chiffres. Ici, le rapport d'un mois clos est enregistré
avec ses données et son PDF, chacun avec son empreinte SHA-256.

UN RAPPORT FIGÉ NE SE MODIFIE PAS : la base refuse UPDATE et DELETE. Une
correction est une nouvelle RÉVISION, avec son motif ; la précédente reste.

AUTOMATIQUE (REPORT_FREEZE_ENABLED) : à partir du 3, pour le mois précédent.
Si iTop ne répond pas, on attend ; le 10, le rapport est figé tel quel et
marqué incomplet. Après le 14, plus rien d'automatique : un mois ancien ne se
fige que sur demande.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import tempfile
from datetime import UTC, datetime

from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, defer

from app.models import ReportSnapshot
from app.services import availability_service, kpi_service, report_service

logger = logging.getLogger(__name__)

REPORT_FREEZE_ENABLED = os.getenv("REPORT_FREEZE_ENABLED", "true").strip().lower() in (
    "1", "true", "yes", "on",
)
FREEZE_FROM_DAY, INCOMPLETE_FROM_DAY, FREEZE_UNTIL_DAY = 3, 10, 14
CHECK_INTERVAL_S = 3600
_LOCK_ID = 7_202_611   # verrou consultatif : un seul processus fige à la fois


class NotFreezable(ValueError):
    """Demande refusée ; le message est affiché tel quel."""


class Corrupted(RuntimeError):
    """Le contenu ne correspond plus à son empreinte."""


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


async def freeze(db: Session, year: int, month: int, *, by: str, reason: str | None = None,
                 now: datetime | None = None) -> dict:
    """Fige le rapport d'un mois clos. Nouvelle révision s'il l'est déjà."""
    now = now or datetime.now(UTC)
    if (year, month) >= (now.year, now.month):
        raise NotFreezable("Le mois n'est pas clos.")
    _lock(db)
    last = _last_revision(db, year, month)
    if last and not (reason or "").strip():
        raise NotFreezable("Ce mois est déjà figé : un motif est requis pour une révision.")

    data = await report_service.collect_report_data(db, month, year)
    if not data["monthly"]["current"]["days_with_data"]:
        raise NotFreezable("Aucune donnée pour ce mois.")
    start, end = (
        datetime.combine(day, datetime.min.time(), tzinfo=UTC)
        for day in kpi_service.month_bounds(year, month)
    )
    # Données seulement, absentes du PDF.
    data["annex"] = {
        "alert_response": _optional(availability_service.alert_response, db, start=start, end=end),
        "tools": _optional(availability_service.tools_health, db, start=start, end=end),
    }
    content = json.dumps(jsonable_encoder(data), ensure_ascii=False, sort_keys=True)
    pdf = await asyncio.to_thread(_pdf_bytes, data)
    row = ReportSnapshot(
        kind="monthly", year=year, month=month, revision=last + 1,
        complete=data.get("itop_error") is None, reason=(reason or "").strip() or None,
        data=content, data_sha256=sha256(content.encode()),
        pdf=pdf, pdf_sha256=sha256(pdf), generated_at=now, generated_by=by,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise NotFreezable("Ce mois vient d'être figé par ailleurs.") from exc
    logger.info("Rapport %02d/%d figé, révision %d (%s)", month, year, row.revision, by)
    return _public(row)


def _lock(db: Session) -> None:
    """Jusqu'à la fin de la transaction. Sans objet hors PostgreSQL (tests)."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": _LOCK_ID})


def _last_revision(db: Session, year: int, month: int) -> int:
    return db.query(func.max(ReportSnapshot.revision)).filter(
        ReportSnapshot.kind == "monthly",
        ReportSnapshot.year == year, ReportSnapshot.month == month,
    ).scalar() or 0


def _optional(read, db, **bounds):
    try:
        return read(db, **bounds)
    except availability_service.HistoryUnavailable:
        return None


def _pdf_bytes(data: dict) -> bytes:
    handle, path = tempfile.mkstemp(suffix=".pdf")
    os.close(handle)
    try:
        report_service.render_pdf(data, path)
        with open(path, "rb") as file:
            return file.read()
    finally:
        with contextlib.suppress(OSError):
            os.remove(path)


def _public(row: ReportSnapshot) -> dict:
    generated = row.generated_at
    return {
        "id": row.id, "year": row.year, "month": row.month, "revision": row.revision,
        "complete": row.complete, "reason": row.reason,
        "generated_at": (generated if generated.tzinfo else generated.replace(tzinfo=UTC))
        .isoformat(),
        "generated_by": row.generated_by,
        "pdf_sha256": row.pdf_sha256, "data_sha256": row.data_sha256,
    }


def list_snapshots(db: Session, limit: int = 120) -> list[dict]:
    rows = db.query(ReportSnapshot).options(
        defer(ReportSnapshot.data), defer(ReportSnapshot.pdf)
    ).order_by(
        ReportSnapshot.year.desc(), ReportSnapshot.month.desc(), ReportSnapshot.revision.desc()
    ).limit(limit).all()
    return [_public(row) for row in rows]


def read(db: Session, snapshot_id: int, part: str) -> tuple[dict, bytes] | None:
    """(description, contenu) ; lève Corrupted si l'empreinte ne correspond pas."""
    row = db.get(ReportSnapshot, snapshot_id)
    if row is None:
        return None
    content, expected = (
        (bytes(row.pdf), row.pdf_sha256) if part == "pdf"
        else (row.data.encode(), row.data_sha256)
    )
    if sha256(content) != expected:
        raise Corrupted(f"rapport {snapshot_id} ({part})")
    return _public(row), content


async def freeze_if_due(now: datetime | None = None) -> bool:
    from app.db.session import SessionLocal

    now = now or datetime.now(UTC)
    if not FREEZE_FROM_DAY <= now.day <= FREEZE_UNTIL_DAY:
        return False
    year, month = kpi_service.previous_month(now.year, now.month)
    db = SessionLocal()
    try:
        if _last_revision(db, year, month):
            return False
        if now.day < INCOMPLETE_FROM_DAY:
            data = await report_service.collect_report_data(db, month, year)
            if data.get("itop_error"):
                logger.info("Rapport %02d/%d : figement reporté, iTop indisponible", month, year)
                return False
        await freeze(db, year, month, by="automatique", now=now)
        return True
    except NotFreezable as exc:
        logger.info("Rapport %02d/%d non figé : %s", month, year, exc)
        return False
    finally:
        db.close()


async def freeze_loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await freeze_if_due()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — la boucle ne meurt jamais
            logger.exception("Figement du rapport mensuel en échec")
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=CHECK_INTERVAL_S)
