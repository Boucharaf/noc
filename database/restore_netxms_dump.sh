#!/usr/bin/env bash
#
# Restore a production NetXMS pg_dump into the local netxms-db container.
#
# ⚠️  This targets the **NetXMS** database (netxms-db, host port 5438) — NOT the
#     dashboard's own database (postgres, host port 5436). Confusing the two
#     would drop the NOC dataset.
#
# The dump is a plain-SQL pg_dump of the ANPTIC production server. It does not
# stand on its own: it assumes an environment that already exists, and it
# carries statements the local image cannot execute. This script builds that
# environment, filters those statements out, and fails loudly on anything else.
#
# What it handles, and why each one is necessary:
#
#   1. Roles. The dump has no CREATE ROLE, but assigns ownership to postgres,
#      netxmsu, siganptic and dev, and grants to arm. Every ALTER ... OWNER TO
#      against a missing role is a hard error, so they are created up front
#      (NOLOGIN, no password — they exist only to own objects).
#
#   2. PostGIS. The dump has no CREATE EXTENSION either, yet declares columns
#      as public.geometry(Point,4326). The extension must therefore be
#      installed *before* the restore, into the public schema.
#
#   3. `CREATE SCHEMA public;`. Point 2 needs the stock public schema to still
#      be there, so this statement is stripped rather than the schema dropped.
#      It is the first error you hit running the dump by hand.
#
#   4. TimescaleDB triggers. 21 log/time-series tables carry a
#      `ts_insert_blocker` trigger calling _timescaledb_functions.insert_blocker().
#      TimescaleDB is not in postgis/postgis:15-3.5-alpine, so these are
#      stripped and the tables restore as plain PostgreSQL tables. No data is
#      lost by doing so — see the warning printed at the end.
#
# Everything else runs under ON_ERROR_STOP=1: if this script reports success,
# the whole dump applied.
#
# Usage:
#   ./database/restore_netxms_dump.sh [DUMP.sql] [options]
#
#   --force       Drop and recreate the target database if it already exists.
#                 Without it, a populated target aborts the run.
#   --dry-run     Run every preflight check and print the plan; change nothing.
#   --keep-timescale-triggers
#                 Do not strip the ts_insert_blocker triggers. Only useful on a
#                 server that actually has TimescaleDB installed.
#   -h/--host, -p/--port, -U/--user, -d/--dbname
#
# Credentials come from .env (NETXMS_DB_*) unless PGPASSWORD is already set.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

DUMP=""
PGHOST_="localhost"
PGPORT_="5438"
PGUSER_="netxms"
PGDATABASE_="netxms"
FORCE=0
DRY_RUN=0
STRIP_TIMESCALE=1

# Roles the dump assigns ownership or grants to. Order is irrelevant; none of
# them own each other.
REQUIRED_ROLES=(postgres netxmsu siganptic dev arm)

die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
warn() { printf '\033[33mwarning:\033[0m %s\n' "$*" >&2; }
info() { printf '\033[36m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m  ✓\033[0m %s\n' "$*"; }

usage() { sed -n '3,47p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --force)   FORCE=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --keep-timescale-triggers) STRIP_TIMESCALE=0; shift ;;
    -h|--host)   PGHOST_="$2"; shift 2 ;;
    -p|--port)   PGPORT_="$2"; shift 2 ;;
    -U|--user)   PGUSER_="$2"; shift 2 ;;
    -d|--dbname) PGDATABASE_="$2"; shift 2 ;;
    --help)      usage ;;
    -*)          die "unknown option: $1 (try --help)" ;;
    *)           DUMP="$1"; shift ;;
  esac
done

# ---------------------------------------------------------------- credentials
# .env is the single source of truth for the compose stack; read it rather than
# duplicating defaults here. Only the NETXMS_DB_* keys are pulled out, so an
# unrelated malformed line cannot break the script.
ENV_FILE="$REPO_ROOT/.env"
if [[ -f "$ENV_FILE" ]]; then
  while IFS='=' read -r key value; do
    value="${value%%$'\r'}"
    case "$key" in
      NETXMS_DB_USER)     : "${PGUSER_:=$value}" ;;
      NETXMS_DB_NAME)     : "${PGDATABASE_:=$value}" ;;
      NETXMS_DB_PASSWORD) : "${PGPASSWORD:=$value}" ;;
    esac
  done < <(grep -E '^NETXMS_DB_(USER|NAME|PASSWORD)=' "$ENV_FILE" || true)
fi

PGUSER_="${PGUSER_:-netxms}"
PGDATABASE_="${PGDATABASE_:-netxms}"
[[ -n "${PGPASSWORD:-}" ]] || die "no password: set PGPASSWORD or NETXMS_DB_PASSWORD in .env"
export PGPASSWORD

DUMP="${DUMP:-$REPO_ROOT/netxmsbd07082026.sql}"

# Connect to the maintenance database for CREATE/DROP DATABASE — you cannot
# drop a database you are currently connected to.
psql_maint() { psql -h "$PGHOST_" -p "$PGPORT_" -U "$PGUSER_" -d postgres -v ON_ERROR_STOP=1 "$@"; }
psql_target() { psql -h "$PGHOST_" -p "$PGPORT_" -U "$PGUSER_" -d "$PGDATABASE_" -v ON_ERROR_STOP=1 "$@"; }

# ------------------------------------------------------------------ preflight
info "Preflight"

[[ -f "$DUMP" ]] || die "dump not found: $DUMP"
DUMP_BYTES=$(stat -c %s "$DUMP")
ok "dump: $DUMP ($(numfmt --to=iec --suffix=B "$DUMP_BYTES" 2>/dev/null || echo "$DUMP_BYTES bytes"))"

head -c 200 "$DUMP" | grep -q "PostgreSQL database dump" \
  || die "$DUMP does not look like a plain-SQL pg_dump"

command -v psql >/dev/null || die "psql not found — install postgresql-client"

psql_maint -tAc 'select 1' >/dev/null 2>&1 \
  || die "cannot connect to $PGUSER_@$PGHOST_:$PGPORT_ — is the netxms-db container up?"
SERVER_VERSION=$(psql_maint -tAc 'show server_version')
ok "server: PostgreSQL $SERVER_VERSION at $PGHOST_:$PGPORT_ as $PGUSER_"

# The dump sets ownership to roles the connecting user does not belong to,
# which only a superuser can do.
[[ "$(psql_maint -tAc "select rolsuper from pg_roles where rolname = current_user")" == "t" ]] \
  || die "$PGUSER_ is not a superuser — the dump's ALTER ... OWNER TO statements will fail"
ok "connecting role is superuser"

psql_maint -tAc "select 1 from pg_available_extensions where name = 'postgis'" | grep -q 1 \
  || die "PostGIS is not available on this server. The dump declares public.geometry
       columns and cannot be restored without it. The netxms-db service must use a
       PostGIS image (postgis/postgis:15-3.5-alpine) — see docker-compose.yml."
ok "postgis extension available"

# A restore roughly doubles on disk before the dump's own indexes are built;
# 3x the dump size is a conservative floor.
NEED_KB=$(( DUMP_BYTES / 1024 * 3 ))
AVAIL_KB=$(df -Pk "$REPO_ROOT" | awk 'NR==2 {print $4}')
if (( AVAIL_KB < NEED_KB )); then
  warn "only $(( AVAIL_KB / 1024 )) MB free where Docker stores its volumes;"
  warn "a restore of this dump wants roughly $(( NEED_KB / 1024 )) MB. Free some space first."
fi

TARGET_EXISTS=$(psql_maint -tAc "select 1 from pg_database where datname = '$PGDATABASE_'" || true)
TARGET_TABLES=0
if [[ "$TARGET_EXISTS" == "1" ]]; then
  TARGET_TABLES=$(psql_target -tAc "select count(*) from information_schema.tables
                                    where table_schema not in ('pg_catalog','information_schema')")
fi

if [[ "$TARGET_EXISTS" == "1" && "$TARGET_TABLES" -gt 0 ]]; then
  # This is the case that makes running the dump by hand dangerous: psql without
  # ON_ERROR_STOP keeps going after every "already exists", and each COPY then
  # *appends* the production rows on top of whatever is already there.
  if [[ "$FORCE" -eq 0 ]]; then
    die "database '$PGDATABASE_' already exists and holds $TARGET_TABLES tables.
       Restoring on top of it would duplicate every row it already has.
       Re-run with --force to drop and recreate it, or pass -d <other-db>."
  fi
  warn "'$PGDATABASE_' holds $TARGET_TABLES tables and --force was given: it will be DROPPED."
fi

if [[ "$STRIP_TIMESCALE" -eq 1 ]]; then
  TS_TRIGGERS=$(grep -c '^CREATE TRIGGER ts_insert_blocker ' "$DUMP" || true)
  ok "will strip $TS_TRIGGERS TimescaleDB ts_insert_blocker trigger(s)"
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  info "Dry run — nothing was changed."
  echo "  would restore : $DUMP"
  echo "  into          : $PGDATABASE_ @ $PGHOST_:$PGPORT_"
  echo "  roles ensured : ${REQUIRED_ROLES[*]}"
  exit 0
fi

# ---------------------------------------------------------------------- roles
info "Ensuring roles the dump assigns objects to"
for role in "${REQUIRED_ROLES[@]}"; do
  # NOLOGIN and passwordless on purpose: these roles exist so that ownership
  # and grants resolve, not so anyone can connect as them. A production restore
  # that needs real logins should provision them separately.
  psql_maint -qc "DO \$\$ BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$role') THEN
                      CREATE ROLE $role NOLOGIN;
                    END IF;
                  END \$\$;"
done
ok "${REQUIRED_ROLES[*]}"

# ------------------------------------------------------------------- database
if [[ "$TARGET_EXISTS" == "1" ]]; then
  info "Dropping '$PGDATABASE_'"
  psql_maint -qc "SELECT pg_terminate_backend(pid) FROM pg_stat_activity
                  WHERE datname = '$PGDATABASE_' AND pid <> pg_backend_pid()" >/dev/null
  psql_maint -qc "DROP DATABASE \"$PGDATABASE_\""
  ok "dropped"
fi

info "Creating '$PGDATABASE_' and installing PostGIS"
psql_maint -qc "CREATE DATABASE \"$PGDATABASE_\" OWNER \"$PGUSER_\" ENCODING 'UTF8'"
# Into public, before the restore: the dump's geometry columns are declared as
# public.geometry and its search_path is empty, so the type must already
# resolve by that exact name.
psql_target -qc "CREATE EXTENSION IF NOT EXISTS postgis"
ok "postgis $(psql_target -tAc "select extversion from pg_extension where extname='postgis'")"

# -------------------------------------------------------------------- restore
info "Restoring (this takes several minutes — the dump is replayed statement by statement)"

# The filters are anchored to the start of a line and to the exact statement
# text pg_dump emits, so COPY data rows cannot be caught by them.
filter() {
  local sed_args=(
    # 1. The stock public schema is kept (it holds PostGIS), so skip recreating it.
    -e '/^CREATE SCHEMA public;$/d'
  )
  if [[ "$STRIP_TIMESCALE" -eq 1 ]]; then
    # 2. Triggers calling into a TimescaleDB that is not installed here.
    sed_args+=(-e '/^CREATE TRIGGER ts_insert_blocker .*_timescaledb_functions\.insert_blocker();$/d')
  fi
  sed "${sed_args[@]}" "$DUMP"
}

START=$(date +%s)
LOG="$(mktemp -t netxms-restore-XXXXXX.log)"

# ON_ERROR_STOP=1 without --single-transaction: a 356 MB restore inside one
# transaction holds locks and WAL for its entire duration, and rolling the whole
# thing back on a late error is slower than starting over from a dropped
# database — which is what --force already does cleanly.
# -o /dev/null discards result rows (the dump's leading set_config() call prints
# one); errors still reach stderr, which is what ON_ERROR_STOP acts on.
if ! filter | psql -h "$PGHOST_" -p "$PGPORT_" -U "$PGUSER_" -d "$PGDATABASE_" \
       -v ON_ERROR_STOP=1 --quiet -o /dev/null -f - 2> >(tee "$LOG" >&2); then
  echo
  die "restore failed — see $LOG (the database is left in place for inspection;
       re-run with --force once the cause is fixed)"
fi

ELAPSED=$(( $(date +%s) - START ))
ok "restore completed in $(( ELAPSED / 60 ))m $(( ELAPSED % 60 ))s"

# --------------------------------------------------------------- verification
info "Verifying"
psql_target -tA -F' ' <<'SQL'
select '  tables       :', count(*) from information_schema.tables
  where table_schema not in ('pg_catalog','information_schema');
select '  schemas      :', string_agg(nspname, ', ' order by nspname) from pg_namespace
  where nspname in ('public','donnebase','equipementinfastructure');
select '  db size      :', pg_size_pretty(pg_database_size(current_database()));
SQL

# Row counts are reported per table rather than in one query on purpose: a
# missing table is information, not a reason to abort a restore that already
# succeeded. Existence is checked in a separate round-trip because PostgreSQL
# resolves every relation in a statement at parse time — a CASE guarding the
# count would still fail on the branch it never takes.
for rel in public.nodes public.object_properties donnebase.ville \
           donnebase.limiteregion donnebase.siteadministratif; do
  if [[ "$(psql_target -tAc "select to_regclass('$rel') is not null")" == "t" ]]; then
    count=$(psql_target -tAc "select count(*) from $rel")
  else
    count="ABSENT"
  fi
  printf '  %-28s %s\n' "$rel" "$count"
done

echo
warn "Two things the dump does NOT bring, and one it does:"
cat <<'NOTES'
  • No time-series history. event_log, syslog, snmp_trap_log, idata_sc_* and
    tdata_sc_* are TimescaleDB hypertables in production; their rows live in
    chunks under _timescaledb_internal, which pg_dump did not include. Those
    tables restore structurally empty. Availability KPIs computed from this
    server therefore start accumulating from now, not from the dump's date.
  • No extensions. Anything beyond PostGIS that production relied on is absent.
  • It DOES bring production's users table — real named accounts and their
    password hashes. The local admin account is now production's admin, so
    NETXMS_PASSWORD from .env no longer opens the console. Treat this database
    as carrying real credentials: do not expose port 5438 beyond localhost.
NOTES

echo
info "Next: rebuild the dashboard's dimensions from this data"
echo "  docker compose exec etl-worker python rebuild_geography.py          # dry run"
echo "  docker compose exec etl-worker python rebuild_geography.py --apply"
echo "  docker compose exec etl-worker python provision_netxms_nodes.py --apply"
