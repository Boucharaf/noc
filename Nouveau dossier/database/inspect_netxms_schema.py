#!/usr/bin/env python3
"""Inspect the local NetXMS PostgreSQL database and show the real schema/data.

Usage examples:
    python database/inspect_netxms_schema.py
    python database/inspect_netxms_schema.py --tables nodes,object_properties,donnebase.ville
    python database/inspect_netxms_schema.py --schema donnebase --sample-limit 10
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Iterable

import psycopg2
from psycopg2 import sql


ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"


def load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def resolve_db_settings() -> dict[str, str]:
    dotenv = load_dotenv(ENV_PATH)
    env = os.environ.copy()
    merged = {**dotenv, **{k: v for k, v in env.items() if v is not None}}

    return {
        "host": merged.get("NETXMS_DB_HOST", "netxms-db"),
        "port": merged.get("NETXMS_DB_PORT", "5432"),
        "dbname": merged.get("NETXMS_DB_NAME", "netxms"),
        "user": merged.get("NETXMS_DB_USER", "netxms"),
        "password": merged.get("NETXMS_DB_PASSWORD", ""),
    }


def dsn_from_settings(settings: dict[str, str]) -> str:
    return (
        f"host={settings['host']} "
        f"port={settings['port']} "
        f"dbname={settings['dbname']} "
        f"user={settings['user']} "
        f"password={settings['password']}"
    )


def fetch_all(conn, query: str, params: tuple | None = None):
    with conn.cursor() as cur:
        cur.execute(query, params or ())
        return cur.fetchall()


def list_schemas(conn) -> list[str]:
    rows = fetch_all(
        conn,
        """
        SELECT schema_name
        FROM information_schema.schemata
        WHERE schema_name NOT IN ('pg_catalog', 'information_schema')
        ORDER BY schema_name
        """,
    )
    return [row[0] for row in rows]


def list_tables(conn, schema: str | None = None) -> list[tuple[str, str]]:
    if schema:
        rows = fetch_all(
            conn,
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema = %s
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """,
            (schema,),
        )
    else:
        rows = fetch_all(
            conn,
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
              AND table_type = 'BASE TABLE'
            ORDER BY table_schema, table_name
            """,
        )
    return [(row[0], row[1]) for row in rows]


def table_columns(conn, schema: str, table: str) -> list[tuple[str, str, str]]:
    rows = fetch_all(
        conn,
        """
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
        """,
        (schema, table),
    )
    return [(row[0], row[1], row[2]) for row in rows]


def table_count(conn, schema: str, table: str) -> int:
    q = sql.SQL("SELECT count(*) FROM {schema}.{table}").format(
        schema=sql.Identifier(schema),
        table=sql.Identifier(table),
    )
    return fetch_all(conn, q.as_string(conn))[0][0]


def sample_rows(conn, schema: str, table: str, limit: int = 5) -> list[tuple]:
    q = sql.SQL("SELECT * FROM {schema}.{table} LIMIT %s").format(
        schema=sql.Identifier(schema),
        table=sql.Identifier(table),
    )
    return fetch_all(conn, q.as_string(conn), (limit,))


def print_summary(conn, schema: str | None = None) -> None:
    print("SCHEMAS")
    print("-------")
    for s in list_schemas(conn):
        print(f"- {s}")
    print()

    tables = list_tables(conn, schema)
    print("TABLES")
    print("------")
    for s, t in tables:
        count = table_count(conn, s, t)
        print(f"- {s}.{t}  rows={count}")
    print()


def print_table_details(conn, schema: str, table: str, sample_limit: int) -> None:
    cols = table_columns(conn, schema, table)
    count = table_count(conn, schema, table)

    print(f"TABLE: {schema}.{table}")
    print(f"ROWS: {count}")
    print("COLUMNS")
    print("--------")
    for col_name, data_type, nullable in cols:
        print(f"- {col_name}: {data_type} (nullable={nullable})")
    print()

    print(f"SAMPLE ROWS (limit={sample_limit})")
    print("--------------------------------")
    rows = sample_rows(conn, schema, table, sample_limit)
    if not rows:
        print("(no rows)")
    else:
        for row in rows:
            print(row)
    print()


def normalize_target_list(raw: str | None) -> list[str]:
    if raw is None:
        return []
    pairs = []
    for item in raw.split(","):
        value = item.strip()
        if value:
            pairs.append(value)
    return pairs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", help="Limit inspection to one schema, e.g. donnebase")
    parser.add_argument(
        "--tables",
        help="Comma-separated table list, e.g. nodes,object_properties,donnebase.ville",
    )
    parser.add_argument("--sample-limit", type=int, default=5, help="Row sample count")
    args = parser.parse_args()

    settings = resolve_db_settings()
    conn = psycopg2.connect(dsn_from_settings(settings))
    try:
        if args.tables:
            targets = normalize_target_list(args.tables)
            for target in targets:
                if "." in target:
                    schema, table = target.split(".", 1)
                else:
                    schema = args.schema or "public"
                    table = target
                print_table_details(conn, schema, table, args.sample_limit)
            return

        print_summary(conn, args.schema)
        if args.schema:
            print(f"Schema inspection: {args.schema}")
            for _, table in list_tables(conn, args.schema):
                print_table_details(conn, args.schema, table, args.sample_limit)
        else:
            # show detail for the most likely NetXMS reference tables first
            priority = [
                ("donnebase", "ville"),
                ("donnebase", "limiteregion"),
                ("donnebase", "siteadministratif"),
                ("public", "nodes"),
                ("public", "object_properties"),
            ]
            seen = set()
            for schema, table in priority:
                if (schema, table) not in seen:
                    seen.add((schema, table))
                    if any((s, t) == (schema, table) for s, t in list_tables(conn)):
                        print_table_details(conn, schema, table, args.sample_limit)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
