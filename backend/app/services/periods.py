"""
Bornes de période et libellés de mois.

Toutes les dates de l'entrepôt sont des TIMESTAMPTZ (voir
etl/sql/schema_facts.sql). Les bornes calculées ici sont donc toujours
« aware » : comparer un timestamptz PostgreSQL à un datetime naïf produit
un décalage silencieux d'un fuseau, jamais une erreur — c'est le genre de
bug qui se voit seulement en fin de mois.
"""
from __future__ import annotations

import calendar
from datetime import UTC, datetime, timedelta

MONTH_LABELS_FR = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)


def month_bounds(month: int, year: int) -> tuple[datetime, datetime]:
    """Retourne [début, fin[ du mois, en UTC."""
    if not 1 <= month <= 12:
        raise ValueError("Mois invalide")
    start = datetime(year, month, 1, tzinfo=UTC)
    last_day = calendar.monthrange(year, month)[1]
    end = start + timedelta(days=last_day)
    return start, end


def previous_month(month: int, year: int) -> tuple[int, int]:
    return (12, year - 1) if month == 1 else (month - 1, year)


def shift_month(month: int, year: int, delta: int) -> tuple[int, int]:
    """Décale de `delta` mois (delta négatif = vers le passé)."""
    index = (year * 12 + (month - 1)) + delta
    return index % 12 + 1, index // 12


def month_label(month: int, year: int) -> str:
    return f"{MONTH_LABELS_FR[month - 1]} {year}"


def period_payload(month: int, year: int) -> dict:
    return {"month": month, "year": year, "label": month_label(month, year)}


def month_minutes(month: int, year: int) -> int:
    return calendar.monthrange(year, month)[1] * 24 * 60


def elapsed_minutes(month: int, year: int) -> int:
    """Minutes réellement écoulées dans le mois.

    Pour le mois en cours, diviser par la durée totale du mois écraserait
    le taux de disponibilité (on compterait comme « temps de service » des
    heures qui ne sont pas encore arrivées).
    """
    start, end = month_bounds(month, year)
    now = datetime.now(UTC)
    horizon = min(end, now) if now > start else end
    return max(1, int((horizon - start).total_seconds() // 60))
