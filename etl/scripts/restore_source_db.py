"""
Restaure un dump PostgreSQL (pg_dump/pg_restore) d'un outil dans un
schéma de staging dédié, utilisé ensuite par extract/db/*.py.

Usage :
    python -m etl.scripts.restore_source_db --tool zabbix --dump /chemin/vers/zabbix.dump

Hypothèse (décision agence) : tous les dumps sources sont au format
PostgreSQL. Si la base native d'un outil est MySQL/MariaDB (Centreon,
iTop, Nagios/NDOUtils), la conversion vers un dump compatible PostgreSQL
doit être faite en amont (ex. pgloader) — ce script ne fait que la partie
restauration PostgreSQL -> schéma de staging, il ne convertit rien.
"""
from __future__ import annotations

import argparse
import subprocess
import sys

_ALLOWED_TOOLS = {"zabbix", "itop", "netxms", "centreon", "nagios"}


def restore(tool: str, dump_path: str, warehouse_dsn: str):
    if tool not in _ALLOWED_TOOLS:
        raise ValueError(f"Outil inconnu: {tool} (attendu: {sorted(_ALLOWED_TOOLS)})")

    schema = f"staging_{tool}"

    # 1. (re)crée un schéma de staging propre
    subprocess.run(
        ["psql", warehouse_dsn, "-c", f"DROP SCHEMA IF EXISTS {schema} CASCADE; CREATE SCHEMA {schema};"],
        check=True,
    )

    # 2. restaure le dump dans ce schéma uniquement (--schema n'existe pas
    #    nativement pour changer le schéma cible : on passe par
    #    --no-owner + un search_path dédié à la connexion de restauration)
    subprocess.run(
        [
            "pg_restore",
            "--no-owner",
            "--no-privileges",
            f"--dbname={warehouse_dsn}",
            "--schema=public",  # le dump source est généralement en `public` -> à rapatrier
            dump_path,
        ],
        check=True,
    )
    print(f"Dump {dump_path} restauré (schéma cible : {schema}). "
          f"Vérifier que les tables sont bien accessibles depuis {schema} "
          f"avant d'activer {tool.upper()}_DB_RESTORE_ENABLED=true.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool", required=True, choices=sorted(_ALLOWED_TOOLS))
    parser.add_argument("--dump", required=True, help="Chemin vers le fichier pg_dump")
    parser.add_argument("--warehouse-dsn", required=True)
    args = parser.parse_args()
    try:
        restore(args.tool, args.dump, args.warehouse_dsn)
    except subprocess.CalledProcessError as exc:
        print(f"Échec de la restauration : {exc}", file=sys.stderr)
        sys.exit(1)
