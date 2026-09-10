"""
Rapport mensuel d'exploitation, en PDF et DOCX.

D'OÙ VIENNENT LES CHIFFRES. Le rapport est construit à partir des MÊMES
services que le tableau de bord — jamais de requêtes SQL parallèles écrites
pour l'occasion. Un chiffre imprimé et un chiffre affiché à l'écran qui
divergent d'un point sont le meilleur moyen de faire perdre toute confiance
dans les deux.

CE QUE LE RAPPORT PEUT DIRE, ET CE QU'IL NE PEUT PLUS. Les agrégats
journaliers (`kpi_daily`) donnent l'évolution, les moyennes et le classement
des sites. Ils ne permettent PAS de lister les incidents d'un mois un par
un : cet historique appartient aux outils sources, qui le conservent mieux
que nous. Le rapport porte donc sur ce que le NOC mesure — sa disponibilité,
ses délais, ses causes — et non sur un inventaire d'événements que Zabbix
sait déjà produire.

C'est un rapport d'EXPLOITATION, pas un journal d'événements. La distinction
est assumée, et elle est écrite dans le document lui-même.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import REPORT_ORGANISATION, REPORT_OUTPUT_DIR
from app.services import kpi_service, sla_service

logger = logging.getLogger(__name__)

MONTHS_FR = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)


def month_label(month: int, year: int) -> str:
    return f"{MONTHS_FR[month - 1]} {year}"


def collect_report_data(db: Session, month: int, year: int) -> dict:
    """Rassemble les données du rapport depuis les services du dashboard."""
    monthly = kpi_service.monthly_summary(db, year, month)
    days_in_period = 31

    return {
        "organisation": REPORT_ORGANISATION,
        "generated_at": datetime.now(timezone.utc),
        "period": month_label(month, year),
        "month": month,
        "year": year,
        "monthly": monthly,
        "trend": kpi_service.trend(db, days=days_in_period),
        "sites": kpi_service.sites_ranking(db, days=days_in_period, limit=15),
        "causes": kpi_service.causes(db, days=days_in_period),
        "resolution": kpi_service.resolution_times(db, days=days_in_period),
        "sla": sla_service.compliance(db, days=days_in_period),
        "breaches": sla_service.breaches(db, days=days_in_period, limit=15),
    }


def _ensure_output_dir() -> str:
    os.makedirs(REPORT_OUTPUT_DIR, exist_ok=True)
    return REPORT_OUTPUT_DIR


def _filename(month: int, year: int, extension: str) -> str:
    return os.path.join(
        _ensure_output_dir(), f"rapport-noc-{year}-{month:02d}.{extension}"
    )


def _fmt(value, suffix: str = "", default: str = "—") -> str:
    """Valeur formatée, avec un tiret cadratin quand elle est absente.

    Un « 0 » à la place d'une donnée manquante est un mensonge : il se lit
    « aucun incident » là où la vérité est « nous ne savons pas ». Le tiret
    dit qu'on ne sait pas.
    """
    if value is None:
        return default
    if isinstance(value, float):
        return f"{value:.2f}{suffix}"
    return f"{value}{suffix}"


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
    # explicitement, sinon chaque accent français lève une UnicodeEncodeError
    # au moment de l'écriture.
    def _txt(value) -> str:
        return str(value).encode("latin-1", "replace").decode("latin-1")

    # fpdf2 >= 2.7 déprécie l'argument `ln=` de cell() : selon la version il
    # est ignoré, le curseur reste alors collé à la marge droite et l'appel
    # multi_cell() suivant échoue avec « Not enough horizontal space ». On
    # pilote donc le retour à la ligne à la main.
    def _newline(height: float = 6) -> None:
        pdf.ln(height)
        pdf.set_x(pdf.l_margin)

    def _line(text: str, height: float = 6) -> None:
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, height, _txt(text))

    def _row(cells, height: float = 6, border: int = 0) -> None:
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
    _line(f"Rapport d'exploitation NOC — {data['period']}", 10)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(110, 110, 110)
    _line(
        f"{data['organisation']} — généré le "
        f"{data['generated_at'].strftime('%d/%m/%Y à %H:%M UTC')}"
    )
    pdf.set_text_color(0, 0, 0)

    # -- 1. Indicateurs ---------------------------------------------------
    _section("1. Indicateurs du mois")
    current = data["monthly"]["current"]
    previous = data["monthly"]["previous"]
    delta = data["monthly"]["delta"]

    _row([(90, "Indicateur", "L"), (35, "Mois", "R"), (35, "Précédent", "R"), (30, "Écart", "R")], border=1)
    for key, label, suffix in (
        ("availability_pct", "Disponibilité du parc", " %"),
        ("avg_alerts", "Alertes actives (moyenne)", ""),
        ("avg_critical", "Alertes critiques (moyenne)", ""),
        ("avg_down", "Équipements en panne (moyenne)", ""),
    ):
        _row(
            [
                (90, label, "L"),
                (35, _fmt(current.get(key), suffix), "R"),
                (35, _fmt(previous.get(key), suffix), "R"),
                (30, _fmt(delta.get(key)), "R"),
            ]
        )

    if not data["monthly"]["reliable"]:
        pdf.set_font("Helvetica", "I", 9)
        _line(
            f"Attention : seulement {current['days_with_data']} jour(s) de "
            "données sur ce mois. Les moyennes ci-dessus ne sont pas "
            "comparables à celles d'un mois complet.",
            5,
        )
        pdf.set_font("Helvetica", "", 10)

    # -- 2. Délais --------------------------------------------------------
    _section("2. Délais de traitement")
    resolution = data["resolution"]
    _row([(110, "Délai moyen de prise en charge (MTTA)", "L"),
          (60, _fmt(resolution.get("mtta_minutes"), " min"), "L")])
    _row([(110, "Délai moyen de résolution (MTTR)", "L"),
          (60, _fmt(resolution.get("mttr_minutes"), " min"), "L")])
    _row([(110, "Alertes traitées par le NOC", "L"),
          (60, _fmt(resolution.get("handled_alerts")), "L")])

    # -- 3. Respect des engagements ---------------------------------------
    _section("3. Respect des engagements de service")
    _row([(30, "Gravité", "L"), (30, "Alertes", "R"), (35, "MTTA", "R"),
          (35, "MTTR", "R"), (40, "Objectif MTTR", "R")], border=1)
    for row in data["sla"]["by_severity"]:
        _row(
            [
                (30, row["severity"], "L"),
                (30, str(row["alerts"]), "R"),
                (35, _fmt(row.get("mtta_minutes"), " min"), "R"),
                (35, _fmt(row.get("mttr_minutes"), " min"), "R"),
                (40, _fmt(row.get("ttr_target_minutes"), " min"), "R"),
            ]
        )

    # -- 4. Sites ---------------------------------------------------------
    _section("4. Sites les plus affectés")
    if data["sites"]:
        _row([(70, "Site", "L"), (40, "Disponibilité", "R"),
              (40, "Alertes (moy.)", "R"), (40, "En panne (moy.)", "R")], border=1)
        for site in data["sites"]:
            _row(
                [
                    (70, site["site"] or "—", "L"),
                    (40, _fmt(site.get("availability_pct"), " %"), "R"),
                    (40, _fmt(site.get("avg_alerts")), "R"),
                    (40, _fmt(site.get("avg_down")), "R"),
                ]
            )
    else:
        _line("Aucune donnée par site sur la période.")

    # -- 5. Causes --------------------------------------------------------
    _section("5. Causes retenues par les exploitants")
    if data["causes"]:
        for cause in data["causes"]:
            _row([(120, cause["cause"], "L"),
                  (30, str(cause["count"]), "R"),
                  (30, f"{cause['share_pct']} %", "R")])
    else:
        _line(
            "Aucune cause renseignée sur la période. La cause est saisie à la "
            "clôture d'une alerte ; c'est la seule donnée d'analyse dont le "
            "NOC est propriétaire."
        )

    # -- 6. Dépassements --------------------------------------------------
    _section("6. Dépassements d'objectif")
    if data["breaches"]:
        for breach in data["breaches"]:
            _line(
                f"{breach['node_name'] or '—'} — {breach['severity']} — "
                f"{breach['ttr_minutes']} min (objectif {breach['target_minutes']} min, "
                f"dépassement {breach['overrun_minutes']} min)",
                5,
            )
    else:
        _line("Aucun dépassement enregistré sur la période.")

    # -- Note de méthode --------------------------------------------------
    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(110, 110, 110)
    _line(
        "Méthode : ce rapport porte sur ce que le NOC mesure — disponibilité "
        "du parc, délais de traitement, causes retenues. Le détail événement "
        "par événement reste consultable dans les outils de supervision "
        "(Zabbix, Centreon) et dans l'ITSM (iTop), qui en sont les sources "
        "de référence.",
        4,
    )
    pdf.set_text_color(0, 0, 0)

    path = _filename(month, year, "pdf")
    pdf.output(path)
    logger.info("Rapport PDF généré : %s", path)
    return path


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------
def generate_docx(db: Session, month: int, year: int) -> str:
    from docx import Document
    from docx.shared import Pt

    data = collect_report_data(db, month, year)
    document = Document()

    document.add_heading(f"Rapport d'exploitation NOC — {data['period']}", level=0)
    subtitle = document.add_paragraph(
        f"{data['organisation']} — généré le "
        f"{data['generated_at'].strftime('%d/%m/%Y à %H:%M UTC')}"
    )
    subtitle.runs[0].font.size = Pt(9)

    def _table(headers: list[str], rows: list[list[str]]) -> None:
        table = document.add_table(rows=1, cols=len(headers))
        table.style = "Light Grid Accent 1"
        for index, header in enumerate(headers):
            table.rows[0].cells[index].text = header
        for row in rows:
            cells = table.add_row().cells
            for index, value in enumerate(row):
                cells[index].text = str(value)

    document.add_heading("1. Indicateurs du mois", level=1)
    current, previous, delta = (
        data["monthly"]["current"],
        data["monthly"]["previous"],
        data["monthly"]["delta"],
    )
    _table(
        ["Indicateur", "Mois", "Précédent", "Écart"],
        [
            [label, _fmt(current.get(key), suffix), _fmt(previous.get(key), suffix), _fmt(delta.get(key))]
            for key, label, suffix in (
                ("availability_pct", "Disponibilité du parc", " %"),
                ("avg_alerts", "Alertes actives (moyenne)", ""),
                ("avg_critical", "Alertes critiques (moyenne)", ""),
                ("avg_down", "Équipements en panne (moyenne)", ""),
            )
        ],
    )
    if not data["monthly"]["reliable"]:
        warning = document.add_paragraph(
            f"Attention : seulement {current['days_with_data']} jour(s) de données "
            "sur ce mois. Les moyennes ne sont pas comparables à un mois complet."
        )
        warning.runs[0].italic = True

    document.add_heading("2. Délais de traitement", level=1)
    resolution = data["resolution"]
    _table(
        ["Indicateur", "Valeur"],
        [
            ["Délai moyen de prise en charge (MTTA)", _fmt(resolution.get("mtta_minutes"), " min")],
            ["Délai moyen de résolution (MTTR)", _fmt(resolution.get("mttr_minutes"), " min")],
            ["Alertes traitées par le NOC", _fmt(resolution.get("handled_alerts"))],
        ],
    )

    document.add_heading("3. Respect des engagements de service", level=1)
    _table(
        ["Gravité", "Alertes", "MTTA", "MTTR", "Objectif MTTR"],
        [
            [
                row["severity"],
                row["alerts"],
                _fmt(row.get("mtta_minutes"), " min"),
                _fmt(row.get("mttr_minutes"), " min"),
                _fmt(row.get("ttr_target_minutes"), " min"),
            ]
            for row in data["sla"]["by_severity"]
        ],
    )

    document.add_heading("4. Sites les plus affectés", level=1)
    if data["sites"]:
        _table(
            ["Site", "Disponibilité", "Alertes (moy.)", "En panne (moy.)"],
            [
                [
                    site["site"] or "—",
                    _fmt(site.get("availability_pct"), " %"),
                    _fmt(site.get("avg_alerts")),
                    _fmt(site.get("avg_down")),
                ]
                for site in data["sites"]
            ],
        )
    else:
        document.add_paragraph("Aucune donnée par site sur la période.")

    document.add_heading("5. Causes retenues par les exploitants", level=1)
    if data["causes"]:
        _table(
            ["Cause", "Occurrences", "Part"],
            [[c["cause"], c["count"], f"{c['share_pct']} %"] for c in data["causes"]],
        )
    else:
        document.add_paragraph(
            "Aucune cause renseignée sur la période. La cause est saisie à la "
            "clôture d'une alerte ; c'est la seule donnée d'analyse dont le NOC "
            "est propriétaire."
        )

    document.add_heading("6. Dépassements d'objectif", level=1)
    if data["breaches"]:
        _table(
            ["Équipement", "Gravité", "MTTR", "Objectif", "Dépassement"],
            [
                [
                    b["node_name"] or "—",
                    b["severity"],
                    f"{b['ttr_minutes']} min",
                    f"{b['target_minutes']} min",
                    f"{b['overrun_minutes']} min",
                ]
                for b in data["breaches"]
            ],
        )
    else:
        document.add_paragraph("Aucun dépassement enregistré sur la période.")

    note = document.add_paragraph(
        "Méthode : ce rapport porte sur ce que le NOC mesure — disponibilité du "
        "parc, délais de traitement, causes retenues. Le détail événement par "
        "événement reste consultable dans les outils de supervision (Zabbix, "
        "Centreon) et dans l'ITSM (iTop), qui en sont les sources de référence."
    )
    note.runs[0].font.size = Pt(8)
    note.runs[0].italic = True

    path = _filename(month, year, "docx")
    document.save(path)
    logger.info("Rapport DOCX généré : %s", path)
    return path


def generate(db: Session, month: int, year: int, output_format: str) -> str:
    if output_format == "pdf":
        return generate_pdf(db, month, year)
    if output_format == "docx":
        return generate_docx(db, month, year)
    raise ValueError(f"Format inconnu : {output_format}")
