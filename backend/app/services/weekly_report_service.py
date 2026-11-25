"""
Rapport hebdomadaire d'exploitation, envoyé par courriel (AM-27).

Une page PDF pour la direction, chaque lundi matin, sur les sept jours
écoulés : disponibilité (pondérée par le temps supervisé), pannes, MTTR et
MTBF techniques, incidents iTop et respect des SLA, et les dix équipements
les moins disponibles. Les chiffres sont ceux des écrans — mêmes services,
mêmes règles (épisodes de panne, non supervisés à part).

UN SEUL ENVOI PAR SEMAINE, quel que soit le nombre de processus backend :
un verrou Redis par semaine ISO (SET NX) désigne celui qui envoie.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import tempfile
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.services import availability_service, incident_service, live_service, pdf_font

logger = logging.getLogger(__name__)

WEEKLY_REPORT_ENABLED = os.getenv("WEEKLY_REPORT_ENABLED", "false").strip().lower() in (
    "1", "true", "yes", "on",
)
# Lundi (0) à 07:00, heure du Burkina Faso (GMT).
WEEKLY_REPORT_WEEKDAY = int(os.getenv("WEEKLY_REPORT_WEEKDAY", "0"))
WEEKLY_REPORT_HOUR = int(os.getenv("WEEKLY_REPORT_HOUR", "7"))
CHECK_INTERVAL_S = 600
LOCK_KEY = "report:weekly:{week}"


def recipients() -> list[str]:
    """WEEKLY_REPORT_RECIPIENTS, sinon les destinataires des notifications."""
    explicit = [
        item.strip() for item in os.getenv("WEEKLY_REPORT_RECIPIENTS", "").split(",")
        if item.strip()
    ]
    if explicit:
        return explicit
    from app.services.notification_service import email_recipients

    return email_recipients()


async def collect(db: Session, end: datetime | None = None) -> dict:
    """Données des sept jours qui précèdent `end` (maintenant par défaut)."""
    end = end or datetime.now(UTC)
    start = end - timedelta(days=7)
    data: dict = {"start": start, "end": end, "generated_at": datetime.now(UTC)}
    try:
        data["availability"] = availability_service.ranking(db, "node", days=7, limit=10)
    except availability_service.HistoryUnavailable:
        data["availability"] = None
    try:
        data["incidents"] = await incident_service.incident_kpis(
            db, start_at=start, end_at=end
        )
        data["sla"] = (
            await incident_service.sla_by_group(db, "region", start_at=start, end_at=end)
        ).get("totals")
    except (incident_service.IncidentsUnavailable, live_service.SnapshotUnavailable):
        data["incidents"] = data["sla"] = None
    return data


def _fmt_pct(value) -> str:
    return "—" if value is None else f"{value:.2f} %".replace(".", ",")


def _fmt_minutes(value) -> str:
    if value is None:
        return "—"
    minutes = float(value)
    if minutes < 60:
        return f"{minutes:.0f} min"
    if minutes < 1440:
        return f"{minutes // 60:.0f} h {minutes % 60:02.0f}"
    return f"{minutes / 1440:.1f} j".replace(".", ",")


def render_pdf(data: dict) -> str:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    font, txt = pdf_font.setup(pdf)
    pdf.set_font(font, "B", 15)
    pdf.cell(0, 9, txt("NOC ANPTIC — rapport hebdomadaire"))
    pdf.ln(9)
    pdf.set_font(font, "", 10)
    period = f"du {data['start']:%d/%m/%Y %H:%M} au {data['end']:%d/%m/%Y %H:%M} (GMT)"
    pdf.cell(0, 6, txt(period))
    pdf.ln(10)

    def section(title: str) -> None:
        pdf.set_font(font, "B", 12)
        pdf.cell(0, 7, txt(title))
        pdf.ln(8)
        pdf.set_font(font, "", 10)

    def line(label: str, value: str) -> None:
        pdf.cell(95, 6, txt(label))
        pdf.cell(0, 6, txt(value))
        pdf.ln(6)

    availability = data.get("availability")
    section("Disponibilité des équipements")
    if availability and availability.get("available"):
        line(
            "Disponibilité (pondérée par le temps supervisé)",
            _fmt_pct(availability.get("average_pct")),
        )
        line("Équipements supervisés", str(availability.get("subjects", 0)))
        unsupervised = (availability.get("basis") or {}).get("unsupervised", 0)
        line("Équipements non supervisés (comptés à part)", str(unsupervised))
        line("Pannes (épisodes continus)", str(availability.get("failures", 0)))
        line("MTTR technique", _fmt_minutes(availability.get("mttr_minutes")))
        mtbf = availability.get("mtbf_hours")
        line("MTBF technique", _fmt_minutes(mtbf * 60 if mtbf is not None else None))
    else:
        line("Journal historique", "indisponible")
    pdf.ln(3)

    section("Incidents iTop et SLA")
    incidents, sla = data.get("incidents"), data.get("sla")
    if incidents:
        line("Tickets ouverts sur la semaine", str(incidents.get("total", 0)))
        rate = _fmt_pct(incidents.get("resolution_rate_pct"))
        line("Résolus", f"{incidents.get('resolved', 0)} ({rate})")
        line("Délais non tenus", str(incidents.get("breached", 0)))
        if sla:
            line("Respect des SLA (cible 95 %)", _fmt_pct(sla.get("compliance_pct")))
            line("Prise en charge moyenne (TTO)", _fmt_minutes(sla.get("mtto_minutes")))
            line("Résolution moyenne (TTR)", _fmt_minutes(sla.get("mttr_minutes")))
    else:
        line("Historique iTop", "indisponible au moment de la génération")
    pdf.ln(3)

    section("Les 10 équipements les moins disponibles")
    rows = (availability or {}).get("rows") or []
    if rows:
        pdf.set_font(font, "B", 9)
        heads = ((80, "Équipement"), (50, "Site"), (30, "Disponibilité"), (25, "Pannes"))
        for width, head in heads:
            pdf.cell(width, 6, txt(head), border=1)
        pdf.ln(6)
        pdf.set_font(font, "", 9)
        for row in rows[:10]:
            pdf.cell(80, 6, txt((row.get("name") or "")[:42]), border=1)
            pdf.cell(50, 6, txt((row.get("site") or "—")[:26]), border=1)
            pdf.cell(30, 6, txt(_fmt_pct(row.get("availability_pct"))), border=1, align="R")
            pdf.cell(25, 6, txt(row.get("down_count", 0)), border=1, align="R")
            pdf.ln(6)
    else:
        line("Classement", "pas encore d'historique")

    pdf.ln(6)
    pdf.set_font(font, "I", 8)
    pdf.multi_cell(0, 4, txt(
        "Disponibilité = temps où l'équipement répond ÷ temps supervisé. Une panne = un épisode continu "
        "d'indisponibilité : les coupures rapprochées comptent pour une seule panne. Les "
        f"équipements sans observation ne comptent ni en service ni en panne. "
        f"Généré le {data['generated_at']:%d/%m/%Y %H:%M} GMT."
    ))
    handle, path = tempfile.mkstemp(prefix="rapport-hebdo-", suffix=".pdf")
    os.close(handle)
    pdf.output(path)
    return path


async def generate(db: Session) -> str:
    return render_pdf(await collect(db))


def is_due(now: datetime) -> bool:
    """Le créneau d'envoi de la semaine est-il atteint ?"""
    return now.weekday() == WEEKLY_REPORT_WEEKDAY and now.hour >= WEEKLY_REPORT_HOUR


async def send_if_due(now: datetime | None = None) -> bool:
    """Envoie le rapport de la semaine si c'est l'heure et que personne ne
    l'a encore fait. Rend True si CE processus l'a envoyé."""
    from app.db.redis_client import redis_sync
    from app.db.session import SessionLocal
    from app.services.notification_service import deliver_with_attachment

    now = now or datetime.now(UTC)
    if not is_due(now):
        return False
    year, week, _day = now.isocalendar()
    # Verrou de la semaine, posé AVANT l'envoi : deux processus ne peuvent
    # pas l'obtenir tous les deux. Il expire après huit jours.
    if not redis_sync.set(LOCK_KEY.format(week=f"{year}-W{week:02d}"), "1", nx=True,
                          ex=8 * 86400):
        return False
    to = recipients()
    if not to:
        logger.warning("Rapport hebdomadaire : aucun destinataire configuré")
        return False
    db = SessionLocal()
    try:
        path = await generate(db)
    finally:
        db.close()
    try:
        await asyncio.to_thread(
            deliver_with_attachment,
            f"NOC ANPTIC — rapport hebdomadaire, semaine {week:02d}",
            "Bonjour,\n\nVeuillez trouver ci-joint le rapport hebdomadaire d'exploitation du "
            "NOC (disponibilité, pannes, incidents et SLA des sept derniers jours).\n",
            to,
            path,
            f"rapport-noc-{year}-S{week:02d}.pdf",
        )
        logger.info("Rapport hebdomadaire envoyé à %d destinataire(s)", len(to))
        return True
    finally:
        with contextlib.suppress(OSError):
            os.remove(path)


async def weekly_loop(stop: asyncio.Event) -> None:
    """Vérifie toutes les dix minutes si le rapport de la semaine est dû."""
    while not stop.is_set():
        try:
            await send_if_due()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — la boucle ne meurt jamais
            logger.exception("Rapport hebdomadaire : envoi en échec")
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=CHECK_INTERVAL_S)
