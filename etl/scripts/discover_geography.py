"""
Peuple dim_ministry / dim_region / dim_locality à partir de ce que les API
renvoient réellement — pas d'une liste régionale codée en dur.

Source prioritaire : iTop, seul outil du périmètre à porter une notion
explicite d'organisation (`Organization` -> ministère) et de localisation
(`Location` -> localité). C'est la source de vérité pour dim_ministry et
dim_locality tant qu'iTop est disponible.

Source de repli : les groupes d'hôtes Zabbix / groupes Centreon, si leur
nom suit une convention identifiable (ex. préfixe "Ministère:" ou
"Region:") — cette convention réelle n'étant pas encore confirmée, la
fonction `_parse_group_name` ci-dessous est le seul endroit à ajuster une
fois la nomenclature de l'agence connue.

dim_region n'est volontairement PAS pré-remplie avec les 13 régions du
Burkina Faso : elle se construit uniquement à partir de ce que les
localités remontées par iTop (ou les groupes, en repli) désignent
explicitement, pour ne pas imposer une hiérarchie que les données ne
confirment pas.
"""
from __future__ import annotations

import re
from typing import Optional

import psycopg2

_GROUP_PATTERN = re.compile(r"^(Minist[eè]re|Region)\s*[:\-]\s*(.+)$", re.I)


def _parse_group_name(name: str) -> Optional[tuple[str, str]]:
    """Retourne (type, valeur) si le nom de groupe suit une convention
    reconnue, sinon None. Type = 'ministry' | 'region'."""
    match = _GROUP_PATTERN.match(name or "")
    if not match:
        return None
    kind = "ministry" if match.group(1).lower().startswith("minist") else "region"
    return kind, match.group(2).strip()


def discover_from_itop(conn: "psycopg2.extensions.connection", organizations: list[dict], locations: list[dict]):
    with conn.cursor() as cur:
        for org in organizations:
            cur.execute(
                """
                INSERT INTO dim_ministry (external_ref, name) VALUES (%s, %s)
                ON CONFLICT (external_ref) DO UPDATE SET name = EXCLUDED.name
                """,
                (str(org["id"]), org["name"]),
            )
        for loc in locations:
            cur.execute(
                """
                INSERT INTO dim_locality (external_ref, name) VALUES (%s, %s)
                ON CONFLICT (external_ref) DO UPDATE SET name = EXCLUDED.name
                """,
                (str(loc["id"]), loc["name"]),
            )
    conn.commit()


def discover_from_groups(conn: "psycopg2.extensions.connection", group_names: list[str]):
    """Repli si iTop n'expose pas (encore) Organization/Location, ou pour
    compléter avec les groupes Zabbix/Centreon (voir `groups` renvoyé par
    fetch_nodes dans ces deux connecteurs)."""
    with conn.cursor() as cur:
        for name in group_names:
            parsed = _parse_group_name(name)
            if not parsed:
                continue
            kind, value = parsed
            if kind == "ministry":
                cur.execute(
                    "INSERT INTO dim_ministry (name) VALUES (%s) ON CONFLICT DO NOTHING",
                    (value,),
                )
            else:
                cur.execute(
                    "INSERT INTO dim_region (code, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (value.lower(), value),
                )
    conn.commit()
