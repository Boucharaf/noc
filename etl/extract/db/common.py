"""
Utilitaires communs aux lecteurs de BDD restaurées (pg_dump/pg_restore).

Rappel de principe (voir README) : ces lecteurs ne sont JAMAIS la source
principale. Ils tournent uniquement si `<OUTIL>_DB_RESTORE_ENABLED=true`
dans la config, en lecture seule sur un schéma de staging dédié, et leur
sortie passe systématiquement par `transform/dedup.py` avant chargement :
seules les lignes absentes de l'API sont conservées.

Toutes les BDD sources sont supposées restaurées au format PostgreSQL
(pg_dump / pg_restore) dans des schémas de staging séparés (un schéma par
outil, ex. `staging_zabbix`, `staging_itop`...) sur la même instance
Postgres que l'entrepôt, ou une instance dédiée référencée par
`<OUTIL>_DB_DSN`. Si la base native d'un outil n'est pas PostgreSQL
(Centreon/iTop sont nativement MySQL/MariaDB), la conversion vers un
schéma Postgres compatible se fait en amont (hors périmètre de ce
lecteur) — voir scripts/restore_source_db.py.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg2
import psycopg2.extras


class ToolDBUnavailable(RuntimeError):
    """La BDD restaurée d'un outil est absente/injoignable. Ne doit jamais
    interrompre le pipeline : c'est une source secondaire optionnelle."""


@contextmanager
def staging_connection(dsn: str) -> Iterator["psycopg2.extensions.connection"]:
    conn = None
    try:
        conn = psycopg2.connect(dsn, options="-c default_transaction_read_only=on")
        yield conn
    except psycopg2.OperationalError as exc:
        raise ToolDBUnavailable(str(exc)) from exc
    finally:
        if conn is not None:
            conn.close()


def fetch_all(dsn: str, query: str, params: tuple = ()) -> list[dict]:
    with staging_connection(dsn) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]
