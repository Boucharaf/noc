"""
Rapport mensuel d'exploitation, en PDF et DOCX.

Deux déclencheurs :

* à la demande — GET /api/report/monthly, réservé au Directeur et au
  Chef NOC ;
* planifié — l'ETL appelle POST /api/internal/reports/monthly le 1er de
  chaque mois à 02:30 (voir etl/celery_app.py et etl/report_trigger.py).
  C'est ce point d'intégration que le TODO de `report_trigger.py`
  attendait ; l'URL à y renseigner est
  `{BACKEND_INTERNAL_URL}/api/internal/reports/monthly`.

Le rapport est construit à partir des mêmes services que le dashboard :
un chiffre imprimé et un chiffre affiché à l'écran ne doivent jamais
diverger, ce qui serait inévitable avec deux requêtes SQL parallèles.
"""
from __future__ import annotations

import logging
import os
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import REPORT_ORGANISATION, REPORT_OUTPUT_DIR
from app.services import coverage_service, interop_service, kpi_service, sla_service
from app.services.periods import month_label

logger = logging.getLogger(__name__)

KPI_LABELS = {
    "total_incidents": "Incidents détectés",
    "resolved": "Incidents résolus",
    "open": "Incidents en cours",
    "critical": "Incidents critiques",
    "resolution_rate_pct": "Taux de résolution (%)",
    "avg_mttr_minutes": "MTTR moyen (min)",
    "avg_mtta_minutes": "MTTA moyen (min)",
    "network_availability_pct": "Disponibilité réseau (%)",
    "critical_localities": "Sites en difficulté",
    "recurrent_nodes": "Équipements récurrents",
    "off_hours_detected": "Incidents hors heures ouvrées",
}


def collect_report_data(db: Session, month: int, year: int) -> dict:
    summary = kpi_service.get_summary(db, month, year)
    return {
        "period": summary["period"],
        "generated_at": datetime.now(UTC),
        "organisation": REPORT_ORGANISATION,
        "kpi": summary["kpi"],
        "vs_previous_month": summary["vs_previous_month"],
        "localities": kpi_service.get_localities(db, month, year, limit=15),
        "nodes": kpi_service.get_nodes(db, month, year, limit=15),
        "recurrent": kpi_service.get_recurrent(db, month, year),
        "causes": kpi_service.get_causes(db, month, year),
        "ministries": kpi_service.get_ministries(db, month, year),
        "sla": sla_service.get_sla(db, month, year),
        "coverage": coverage_service.get_coverage(db),
        "interop": interop_service.get_interop_status(db, month, year),
    }


def _ensure_output_dir() -> str:
    os.makedirs(REPORT_OUTPUT_DIR, exist_ok=True)
    return REPORT_OUTPUT_DIR


def _filename(month: int, year: int, extension: str) -> str:
    return os.path.join(
        _ensure_output_dir(), f"rapport-noc-{year}-{month:02d}.{extension}"
    )


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
def generate_pdf(db: Session, month: int, year: int) -> str:
    from fpdf import FPDF

    data = collect_report_data(db, month, year)

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Les polices cœur de fpdf2 sont en latin-1 : le texte est transcodé
    # explicitement, sinon chaque accent français lève une
    # UnicodeEncodeError au moment de l'écriture.
    def _txt(value) -> str:
        return str(value).encode("latin-1", "replace").decode("latin-1")

    # fpdf2 >= 2.7 déprécie l'argument `ln=` de cell() : selon la version
    # il est ignoré, le curseur reste alors collé à la marge droite et
    # l'appel multi_cell() suivant échoue avec « Not enough horizontal
    # space ». On pilote donc le retour à la ligne à la main.
    def _newline(height: float = 6) -> None:
        pdf.ln(height)
        pdf.set_x(pdf.l_margin)

    def _line(text: str, height: float = 6) -> None:
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, height, _txt(text))

    def _row(cells: list[tuple[float, str, str]], height: float = 6, border: int = 0) -> None:
        """cells = [(largeur, texte, alignement), ...]"""
        pdf.set_x(pdf.l_margin)
        for width, value, align in cells:
            pdf.cell(width, height, _txt(value), border=border, align=align)
        _newline(height)

    def _section(title: str) -> None:
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 12)
        _line(title, 8)
        pdf.set_font("Helvetica", "", 10)

    pdf.set_font("Helvetica", "B", 16)
    _line(f"Rapport d'exploitation NOC - {month_label(month, year)}", 10)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(110, 110, 110)
    _line(
        f"{data['organisation']} - genere le "
        f"{data['generated_at'].strftime('%d/%m/%Y a %H:%M UTC')}"
    )
    pdf.set_text_color(0, 0, 0)

    _section("1. Indicateurs cles")
    for key, label in KPI_LABELS.items():
        if key in data["kpi"]:
            _row([(110, label, "L"), (60, str(data["kpi"][key]), "L")])

    delta = data["vs_previous_month"]
    pdf.set_font("Helvetica", "I", 9)
    _line(
        f"Evolution vs mois precedent : {delta['incidents_delta']:+d} incident(s), "
        f"{delta['availability_delta']:+.2f} point(s) de disponibilite.",
        5,
    )
    pdf.set_font("Helvetica", "", 10)

    _section("2. Sites les plus touches")
    pdf.set_font("Helvetica", "B", 9)
    _row(
        [(65, "Site", "L"), (42, "Region", "L"), (25, "Incidents", "R"),
         (25, "Resolus", "R"), (25, "MTTR", "R")],
        border=1,
    )
    pdf.set_font("Helvetica", "", 9)
    for row in data["localities"][:12]:
        _row(
            [
                (65, str(row["locality"])[:34], "L"),
                (42, str(row["region"])[:22], "L"),
                (25, str(row["total_incidents"]), "R"),
                (25, str(row["resolved"]), "R"),
                (25, str(row["avg_mttr"]) if row["avg_mttr"] is not None else "-", "R"),
            ],
            border=1,
        )

    _section("3. Causes des incidents")
    pdf.set_font("Helvetica", "B", 9)
    _row(
        [(95, "Cause", "L"), (30, "Nombre", "R"), (30, "Part (%)", "R"), (27, "MTTR", "R")],
        border=1,
    )
    pdf.set_font("Helvetica", "", 9)
    for row in data["causes"]:
        _row(
            [
                (95, str(row["label"])[:52], "L"),
                (30, str(row["total_incidents"]), "R"),
                (30, str(row["share_pct"]), "R"),
                (27, str(row["avg_mttr"]) if row["avg_mttr"] is not None else "-", "R"),
            ],
            border=1,
        )

    _section("4. Respect des engagements de service")
    sla = data["sla"]
    for row in sla["by_severity"]:
        mttr = row["avg_mttr_minutes"] if row["avg_mttr_minutes"] is not None else "-"
        _line(
            f"{row['severity']} : {row['resolved']}/{row['total_incidents']} resolus, "
            f"objectif {row['ttr_target_minutes']} min, MTTR {mttr} min, "
            f"depassements {row['breached']}",
            5,
        )
    if sla["global_compliance_pct"] is not None:
        pdf.set_font("Helvetica", "B", 10)
        _line(f"Conformite globale : {sla['global_compliance_pct']} %")
        pdf.set_font("Helvetica", "", 10)

    _section("5. Couverture de supervision")
    coverage = data["coverage"]
    _line(
        f"{coverage['monitored_assets']} equipement(s) supervise(s) sur "
        f"{coverage['total_assets']} recense(s) - "
        f"{coverage['coverage_pct'] if coverage['coverage_pct'] is not None else '-'} %.",
        5,
    )

    _section("6. Etat des integrations")
    for tool in data["interop"]["tools"]:
        _line(
            f"- {tool['tool']} : {tool['state']} - {tool['detail']} "
            f"({tool['incidents_this_month']} incident(s) ce mois)",
            5,
        )

    path = _filename(month, year, "pdf")
    pdf.output(path)
    logger.info("Rapport PDF genere : %s", path)
    return path


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------
def generate_docx(db: Session, month: int, year: int) -> str:
    from docx import Document
    from docx.shared import Pt

    data = collect_report_data(db, month, year)
    document = Document()

    document.add_heading(f"Rapport d'exploitation NOC — {month_label(month, year)}", level=0)
    subtitle = document.add_paragraph(
        f"{data['organisation']} — généré le "
        f"{data['generated_at'].strftime('%d/%m/%Y à %H:%M UTC')}"
    )
    subtitle.runs[0].font.size = Pt(9)

    document.add_heading("1. Indicateurs clés", level=1)
    table = document.add_table(rows=1, cols=2)
    table.style = "Light Grid Accent 1"
    header = table.rows[0].cells
    header[0].text, header[1].text = "Indicateur", "Valeur"
    for key, label in KPI_LABELS.items():
        if key in data["kpi"]:
            cells = table.add_row().cells
            cells[0].text = label
            cells[1].text = str(data["kpi"][key])

    delta = data["vs_previous_month"]
    document.add_paragraph(
        f"Évolution vs mois précédent : {delta['incidents_delta']:+d} incident(s), "
        f"{delta['availability_delta']:+.2f} point(s) de disponibilité."
    )

    document.add_heading("2. Sites les plus touchés", level=1)
    table = document.add_table(rows=1, cols=5)
    table.style = "Light Grid Accent 1"
    for index, title in enumerate(("Site", "Région", "Incidents", "Résolus", "MTTR (min)")):
        table.rows[0].cells[index].text = title
    for row in data["localities"][:15]:
        cells = table.add_row().cells
        cells[0].text = row["locality"]
        cells[1].text = row["region"]
        cells[2].text = str(row["total_incidents"])
        cells[3].text = str(row["resolved"])
        cells[4].text = str(row["avg_mttr"]) if row["avg_mttr"] is not None else "—"

    document.add_heading("3. Causes des incidents", level=1)
    table = document.add_table(rows=1, cols=3)
    table.style = "Light Grid Accent 1"
    for index, title in enumerate(("Cause", "Nombre", "Part (%)")):
        table.rows[0].cells[index].text = title
    for row in data["causes"]:
        cells = table.add_row().cells
        cells[0].text = row["label"]
        cells[1].text = str(row["total_incidents"])
        cells[2].text = str(row["share_pct"])

    document.add_heading("4. Respect des engagements de service", level=1)
    for row in data["sla"]["by_severity"]:
        document.add_paragraph(
            f"{row['severity']} : {row['resolved']}/{row['total_incidents']} résolus — "
            f"objectif {row['ttr_target_minutes']} min — "
            f"dépassements : {row['breached']}",
            style="List Bullet",
        )

    document.add_heading("5. Couverture de supervision", level=1)
    coverage = data["coverage"]
    document.add_paragraph(
        f"{coverage['monitored_assets']} équipement(s) supervisé(s) sur "
        f"{coverage['total_assets']} recensé(s) — "
        f"{coverage['coverage_pct'] if coverage['coverage_pct'] is not None else '—'} %."
    )

    document.add_heading("6. État des intégrations", level=1)
    for tool in data["interop"]["tools"]:
        document.add_paragraph(
            f"{tool['tool']} : {tool['state']} — {tool['detail']} "
            f"({tool['incidents_this_month']} incident(s) ce mois)",
            style="List Bullet",
        )

    path = _filename(month, year, "docx")
    document.save(path)
    logger.info("Rapport DOCX généré : %s", path)
    return path


def generate(db: Session, month: int, year: int, output_format: str) -> str:
    if output_format == "pdf":
        return generate_pdf(db, month, year)
    if output_format == "docx":
        return generate_docx(db, month, year)
    raise ValueError("Format de rapport non pris en charge.")
