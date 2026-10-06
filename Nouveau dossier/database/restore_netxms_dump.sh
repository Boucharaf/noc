#!/usr/bin/env bash
#
# Restaure le dump de production NetXMS dans la base locale `netxms-db`, le
# purge de ses secrets, et crée le compte de lecture du collecteur.
#
# ⚠️  Cible : la base NetXMS (service netxms-db, 127.0.0.1:5438) — JAMAIS la
#     base du NOC (service postgres, port 5436).
#
# POURQUOI UNE BASE SEULE ET PAS UN SERVEUR NETXMS : voir docker-compose.yml,
# service netxms-db. Un netxmsd démarré sur ces données exécuterait les actions
# de production (courriels, Telegram) vers de vraies personnes.
#
# Le dump est un pg_dump « plain SQL » du serveur de l'agence. Il ne se suffit
# pas à lui-même :
#
#   1. Rôles. Aucun CREATE ROLE, mais des ALTER … OWNER TO et des GRANT vers
#      les rôles de production. Ils sont relevés DANS le dump — une liste
#      écrite à la main en oublie toujours un — et créés avant la restauration
#      (NOLOGIN, sans mot de passe : ils ne servent qu'à posséder des objets).
#   2. PostGIS. Aucun CREATE EXTENSION, mais des colonnes public.geometry :
#      l'extension est installée avant, dans le schéma public.
#   3. TimescaleDB. Les tables de séries temporelles portent un déclencheur
#      ts_insert_blocker vers une extension absente ici : il est retiré, et
#      les tables sont restaurées en tables ordinaires.
#
# Tout le reste s'exécute sous ON_ERROR_STOP=1 : si ce script annonce un
# succès, le dump entier a été appliqué. Puis, après la restauration :
#
#   4. Purge (database/netxms_sanitize.sql) des secrets RÉELS du dump :
#      communautés SNMP, mots de passe SNMPv3, empreintes de mots de passe,
#      jetons des canaux de notification. Aucun n'est utile au NOC.
#   5. Compte de lecture `noc_reader` (database/netxms_readonly_role.sql) :
#      lecture seule, sur les seules colonnes que lit le collecteur. C'est
#      EXACTEMENT le droit à demander à l'agence pour la production.
#
# Usage :
#   docker compose --profile netxms up -d netxms-db
#   ./database/restore_netxms_dump.sh [DUMP.sql] [options]
#
#   --force         Supprime et recrée la base si elle contient déjà des tables.
#   --dry-run       Contrôles préalables et plan, sans rien modifier.
#   --no-sanitize   Ne purge pas les secrets (déconseillé).
#   --keep-timescale-triggers
#                   Garde les déclencheurs TimescaleDB (serveur qui a l'extension).
#
# psql est pris sur l'hôte s'il existe, sinon DANS le conteneur netxms-db :
# rien à installer sous Windows.
#
# Lus dans .env : NETXMS_DB_USER, NETXMS_DB_PASSWORD, NETXMS_DB_NAME,
# NETXMS_DB_READER_PASSWORD.

set -euo pipefail

# Git Bash réécrit les chemins POSIX passés à un exécutable Windows
# (/dev/null devient C:/…) : sans ceci, docker.exe transmettrait au conteneur
# des chemins qui n'y existent pas.
export MSYS_NO_PATHCONV=1

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

DUMP=""
FORCE=0
DRY_RUN=0
SANITIZE=1
STRIP_TIMESCALE=1

die()  { printf '\033[31merreur :\033[0m %s\n' "$*" >&2; exit 1; }
warn() { printf '\033[33mattention :\033[0m %s\n' "$*" >&2; }
info() { printf '\033[36m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m  ✓\033[0m %s\n' "$*"; }

usage() { sed -n '3,50p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --force)       FORCE=1; shift ;;
    --dry-run)     DRY_RUN=1; shift ;;
    --no-sanitize) SANITIZE=0; shift ;;
    --keep-timescale-triggers) STRIP_TIMESCALE=0; shift ;;
    --help|-h)     usage ;;
    -*)            die "option inconnue : $1 (voir --help)" ;;
    *)             DUMP="$1"; shift ;;
  esac
done

# ------------------------------------------------------------- configuration
# .env est la source unique de la pile compose : on le lit plutôt que de
# dupliquer ici des valeurs par défaut qui finiraient par diverger.
env_value() {
  [[ -f .env ]] || return 0
  # `|| true` : une clé absente n'est pas une erreur. Sans lui, pipefail fait
  # échouer l'affectation et set -e arrête le script sans un mot.
  { grep -E "^$1=" .env || true; } | tail -1 | cut -d= -f2- | tr -d '\r'
}

DB_USER="$(env_value NETXMS_DB_USER)";  DB_USER="${DB_USER:-netxms}"
DB_NAME="$(env_value NETXMS_DB_NAME)";  DB_NAME="${DB_NAME:-netxms}"
READER_PASSWORD="$(env_value NETXMS_DB_READER_PASSWORD)"
DUMP="${DUMP:-$REPO_ROOT/database/netxmsbd07082026.sql}"

if command -v psql >/dev/null 2>&1; then
  DB_PASSWORD="$(env_value NETXMS_DB_PASSWORD)"
  export PGPASSWORD="${PGPASSWORD:-${DB_PASSWORD:-netxms}}"
  run_psql() { psql -h 127.0.0.1 -p 5438 -U "$DB_USER" -v ON_ERROR_STOP=1 "$@"; }
  PSQL_WHERE="hôte, 127.0.0.1:5438"
else
  # Connexion locale au conteneur : l'image officielle y accepte le
  # superutilisateur sans mot de passe.
  run_psql() { docker compose exec -T netxms-db psql -U "$DB_USER" -v ON_ERROR_STOP=1 "$@"; }
  PSQL_WHERE="conteneur netxms-db"
fi
psql_maint()  { run_psql -d postgres "$@"; }
psql_target() { run_psql -d "$DB_NAME" "$@"; }
scalar()      { "$@" | tr -d '\r[:space:]'; }

# ---------------------------------------------------------- contrôles préalables
info "Contrôles préalables"

[[ -f "$DUMP" ]] || die "dump introuvable : $DUMP"
DUMP_BYTES=$(wc -c < "$DUMP" | tr -d ' ')
ok "dump : $DUMP ($(( DUMP_BYTES / 1024 / 1024 )) Mo)"
head -c 200 "$DUMP" | grep -q "PostgreSQL database dump" \
  || die "$DUMP n'est pas un pg_dump au format SQL"
ok "psql : $PSQL_WHERE"

psql_maint -tAc 'select 1' >/dev/null 2>&1 \
  || die "connexion impossible à $DB_USER@netxms-db. Démarrer la base :
       docker compose --profile netxms up -d netxms-db"
ok "serveur : PostgreSQL $(scalar psql_maint -tAc 'show server_version')"

[[ "$(scalar psql_maint -tAc "select rolsuper from pg_roles where rolname = current_user")" == "t" ]] \
  || die "$DB_USER n'est pas superutilisateur : les ALTER … OWNER TO du dump échoueraient"
ok "rôle de connexion superutilisateur"

[[ "$(scalar psql_maint -tAc "select count(*) from pg_available_extensions where name = 'postgis'")" == "1" ]] \
  || die "PostGIS indisponible sur ce serveur : l'image de netxms-db doit être postgis/postgis"
ok "extension postgis disponible"

TARGET_EXISTS=$(scalar psql_maint -tAc "select count(*) from pg_database where datname = '$DB_NAME'")
TARGET_TABLES=0
if [[ "$TARGET_EXISTS" == "1" ]]; then
  # Les tables qui APPARTIENNENT à une extension ne comptent pas : l'image
  # postgis/postgis installe d'office postgis_tiger_geocoder et
  # postgis_topology dans la base initiale, soit une quarantaine de tables
  # dans une base par ailleurs vide.
  TARGET_TABLES=$(scalar psql_target -tAc "select count(*) from pg_class c
                                           join pg_namespace n on n.oid = c.relnamespace
                                           where c.relkind in ('r','p')
                                             and n.nspname not in ('pg_catalog','information_schema')
                                             and not exists (select 1 from pg_depend d
                                                             where d.objid = c.oid and d.deptype = 'e')")
fi
if (( TARGET_TABLES > 0 )); then
  # Le cas qui rend une restauration « à la main » dangereuse : sans
  # ON_ERROR_STOP, psql continue après chaque « already exists » et chaque
  # COPY AJOUTE les lignes de production à celles déjà présentes.
  (( FORCE )) || die "la base '$DB_NAME' contient déjà $TARGET_TABLES tables.
       La restaurer par-dessus doublerait chaque ligne. Relancer avec --force
       pour la supprimer et la recréer."
  warn "'$DB_NAME' contient $TARGET_TABLES tables et --force est donné : elle sera SUPPRIMÉE."
fi

# Rôles cités par le dump, relevés dans le dump lui-même.
mapfile -t REQUIRED_ROLES < <(
  grep -E '^(ALTER .+ OWNER TO |GRANT .+ TO |REVOKE .+ FROM |ALTER DEFAULT PRIVILEGES FOR ROLE )' "$DUMP" \
  | sed -E \
      -e 's/ WITH GRANT OPTION;$/;/' \
      -e 's/^ALTER DEFAULT PRIVILEGES FOR ROLE ([^ ]+) .* (TO|FROM) ([^;]+);$/\1,\3/' \
      -e 's/^ALTER .* OWNER TO ([^;]+);$/\1/' \
      -e 's/^GRANT .* TO ([^;]+);$/\1/' \
      -e 's/^REVOKE .* FROM ([^;]+);$/\1/' \
  | tr ',' '\n' \
  | sed -E 's/^[[:space:]]*"?//; s/"?[[:space:]]*$//' \
  | grep -vE '[[:space:]]|^$' \
  | grep -vxE 'PUBLIC|CURRENT_USER|SESSION_USER|CURRENT_ROLE' \
  | sort -u
)
ok "rôles cités par le dump : ${REQUIRED_ROLES[*]:-aucun}"

if (( STRIP_TIMESCALE )); then
  TS_TRIGGERS=$(grep -c '^CREATE TRIGGER ts_insert_blocker ' "$DUMP" || true)
  ok "$TS_TRIGGERS déclencheur(s) TimescaleDB à retirer"
fi

if (( DRY_RUN )); then
  info "Simulation — rien n'a été modifié."
  echo "  restaurerait : $DUMP"
  echo "  dans         : $DB_NAME (netxms-db)"
  echo "  purge        : $([[ $SANITIZE == 1 ]] && echo oui || echo NON)"
  echo "  noc_reader   : $([[ -n $READER_PASSWORD ]] && echo oui || echo 'non (NETXMS_DB_READER_PASSWORD vide)')"
  exit 0
fi

# ---------------------------------------------------------------------- rôles
info "Création des rôles manquants"
{
  for role in "${REQUIRED_ROLES[@]}"; do
    literal=${role//\'/\'\'}
    printf "SELECT format('CREATE ROLE %%I NOLOGIN', '%s') WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '%s')\n\\\\gexec\n" \
      "$literal" "$literal"
  done
} | psql_maint -q >/dev/null
ok "fait"

# -------------------------------------------------------------------- base
if (( TARGET_TABLES > 0 )); then
  info "Suppression de '$DB_NAME'"
  psql_maint -qc "SELECT pg_terminate_backend(pid) FROM pg_stat_activity
                  WHERE datname = '$DB_NAME' AND pid <> pg_backend_pid()" >/dev/null
  psql_maint -qc "DROP DATABASE \"$DB_NAME\""
  TARGET_EXISTS=0
fi
if [[ "$TARGET_EXISTS" != "1" ]]; then
  psql_maint -qc "CREATE DATABASE \"$DB_NAME\" OWNER \"$DB_USER\" ENCODING 'UTF8'"
  ok "base '$DB_NAME' créée"
fi
# Dans public, AVANT la restauration : le dump déclare ses colonnes en
# public.geometry avec un search_path vide, le type doit déjà exister sous ce nom.
psql_target -qc "CREATE EXTENSION IF NOT EXISTS postgis" >/dev/null
ok "postgis $(scalar psql_target -tAc "select extversion from pg_extension where extname='postgis'")"

# ------------------------------------------------------------- restauration
info "Restauration (plusieurs minutes : le dump est rejoué instruction par instruction)"

# Filtres ancrés en début de ligne et sur le texte exact émis par pg_dump :
# une ligne de données d'un COPY ne peut pas être prise par erreur.
filter() {
  local sed_args=(-e '/^CREATE SCHEMA public;$/d')
  if (( STRIP_TIMESCALE )); then
    sed_args+=(-e '/^CREATE TRIGGER ts_insert_blocker .*_timescaledb_functions\.insert_blocker();$/d')
  fi
  sed "${sed_args[@]}" "$DUMP"
}

START=$(date +%s)
LOG="$(mktemp -t netxms-restore-XXXXXX.log)"

# Sans --single-transaction : une transaction unique sur 350 Mo retiendrait
# verrous et WAL toute la durée, et annuler tout sur une erreur tardive est
# plus lent que repartir d'une base supprimée — ce que --force fait proprement.
if ! filter | psql_target --quiet -o /dev/null -f - 2> >(tee "$LOG" >&2); then
  echo
  die "restauration en échec — voir $LOG (la base est laissée en l'état pour
       inspection ; relancer avec --force une fois la cause corrigée)"
fi
ELAPSED=$(( $(date +%s) - START ))
ok "restauration terminée en $(( ELAPSED / 60 )) min $(( ELAPSED % 60 )) s"

# -------------------------------------------------------------------- purge
if (( SANITIZE )); then
  info "Purge des secrets de production"
  psql_target -q -f - < "$REPO_ROOT/database/netxms_sanitize.sql" 2>&1 \
    | sed -n 's/.*NOTICE: *//p' | sed 's/^/    /'
  ok "fait"
else
  warn "--no-sanitize : les secrets de production (SNMP, mots de passe) restent dans la base."
fi

# ------------------------------------------------------------ compte de lecture
if [[ -n "$READER_PASSWORD" ]]; then
  info "Compte de lecture noc_reader"
  psql_target -q -v reader_password="$READER_PASSWORD" -f - \
    < "$REPO_ROOT/database/netxms_readonly_role.sql" >/dev/null
  ok "noc_reader : lecture seule, colonnes utiles au collecteur uniquement"
else
  warn "NETXMS_DB_READER_PASSWORD vide dans .env : compte noc_reader NON créé."
fi

# --------------------------------------------------------------- vérification
info "Vérification"
printf '  %-28s %s\n' "taille de la base" "$(psql_target -tAc "select pg_size_pretty(pg_database_size(current_database()))" | tr -d '\r')"
for query in \
  "équipements (nodes)|select count(*) from public.nodes" \
  "objets non supprimés|select count(*) from public.object_properties where is_deleted = 0" \
  "alarmes actives|select count(*) from public.alarms where (alarm_state & 15) in (0, 1)"; do
  printf '  %-28s %s\n' "${query%%|*}" "$(scalar psql_target -tAc "${query#*|}")"
done

echo
warn "Ce que le dump n'apporte PAS :"
cat <<'NOTES'
  • Aucun historique de mesures. idata_*, tdata_*, event_log, syslog sont des
    hypertables TimescaleDB en production ; leurs lignes vivent dans des
    fragments que pg_dump n'a pas inclus. Ces tables sont restaurées vides.
  • Un instantané FIGÉ au 07/08/2026 : les alarmes « actives » sont celles de
    ce jour-là, et aucune ne changera tant que la base n'est pas remplacée.
NOTES

echo
info "Brancher le collecteur sur cette base (.env), puis redémarrer :"
echo "  NETXMS_API_URL=postgresql://netxms-db:5432/$DB_NAME"
echo "  NETXMS_API_USER=noc_reader"
echo "  NETXMS_API_PASSWORD=<NETXMS_DB_READER_PASSWORD>"
echo "  docker compose up -d collector backend"
