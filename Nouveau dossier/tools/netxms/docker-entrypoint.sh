#!/bin/bash
# Configure netxmsd depuis l'environnement, initialise son schéma PostgreSQL
# au premier démarrage (nxdbmgr init — l'équivalent NetXMS de l'assistant web
# de Centreon ou de l'installateur sans interaction d'iTop), démarre l'API
# Legacy Web sous Tomcat, puis netxmsd au premier plan.
#
# ⚠️ Les chemins des binaires et du fichier de configuration ci-dessous
# reposent sur la convention Debian usuelle (/etc/netxmsd.conf,
# /usr/bin/netxmsd, /usr/bin/nxdbmgr) mais n'ont pas été vérifiés contre le
# contenu réel du paquet Debian `netxms-server` en 5.0.8 — voir la note en
# tête de Dockerfile. `locate_binary` et `locate_config` cherchent aux
# emplacements plausibles et donnent une erreur exploitable (liste du
# contenu du paquet) plutôt qu'un chemin faux silencieux.
set -euo pipefail

log() { echo "[entrypoint] $*"; }
die() { echo "[entrypoint] ERREUR: $*" >&2; exit 1; }

DB_HOST=${NETXMS_SERVER_DB_HOST:-netxms-server-db}
DB_PORT=${NETXMS_SERVER_DB_PORT:-5432}
DB_NAME=${NETXMS_SERVER_DB_NAME:-netxms}
DB_USER=${NETXMS_SERVER_DB_USER:-netxms}
DB_PASSWORD=${NETXMS_SERVER_DB_PASSWORD:-netxms}
TIMEZONE=${TZ:-Africa/Ouagadougou}

CONFIG_FILE=/etc/netxmsd.conf

# ─────────────────────────── localisation des binaires ───────────────────────────
# Le paquet Debian place ses exécutables sous /usr/bin ou /usr/sbin selon les
# versions ; on cherche plutôt que de figer un chemin non confirmé.
locate_binary() {
  local name=$1 found
  found=$(command -v "$name" 2>/dev/null) && { echo "$found"; return 0; }
  found=$(dpkg -L netxms-server 2>/dev/null | grep -E "/bin/${name}\$" | head -1)
  [ -n "$found" ] || die "binaire « ${name} » introuvable dans le paquet netxms-server. \
Contenu du paquet : \$(dpkg -L netxms-server)"
  echo "$found"
}

NETXMSD_BIN=$(locate_binary netxmsd)
NXDBMGR_BIN=$(locate_binary nxdbmgr)
log "netxmsd : ${NETXMSD_BIN} ; nxdbmgr : ${NXDBMGR_BIN}"

# ─────────────────────────── base de données ───────────────────────────
wait_for_db() {
  log "attente de ${DB_HOST}:${DB_PORT}…"
  for _ in $(seq 1 90); do
    if PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
        -tAc 'select 1' >/dev/null 2>&1; then
      log "base de données joignable"
      return 0
    fi
    sleep 2
  done
  die "${DB_HOST}:${DB_PORT}/${DB_NAME} injoignable (ou identifiants erronés) après 180 s"
}

# ─────────────────────────── configuration ───────────────────────────
# Ce fichier est réécrit à CHAQUE démarrage (pas seulement à l'installation) :
# la configuration vit dans l'image et non dans un volume séparé, donc un
# changement de mot de passe de base dans .env doit se répercuter au
# redémarrage sans réinstallation.
write_config() {
  cat > "$CONFIG_FILE" <<CONF
DBDriver = pgsql.ddr
DBServer = ${DB_HOST}
DBName = ${DB_NAME}
DBLogin = ${DB_USER}
DBPassword = ${DB_PASSWORD}
LogFile = {syslog}
LogHistorySize = 1
DailyLogFileSuffix =
ServerName = ${NETXMS_SERVER_NAME:-NOC Laboratoire}
Timezone = ${TIMEZONE}
CONF
  log "netxmsd.conf écrit (base ${DB_NAME}@${DB_HOST})"
}

schema_initialized() {
  PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
    -tAc "select count(*) from pg_tables where schemaname = 'public' and tablename = 'metadata'" \
    2>/dev/null | grep -q '^1$'
}

init_schema() {
  if schema_initialized; then
    log "schéma NetXMS déjà initialisé — nxdbmgr init ignoré"
    return 0
  fi
  log "premier démarrage — initialisation du schéma (nxdbmgr init)…"
  # `-X` : sans interaction. nxdbmgr lit DBDriver/DBServer/… dans
  # netxmsd.conf, comme netxmsd lui-même.
  "$NXDBMGR_BIN" -X -f "$CONFIG_FILE" init \
    || die "nxdbmgr init a échoué — voir les lignes ci-dessus"
  log "schéma initialisé"
}

# ─────────────────────────── API Legacy Web ───────────────────────────
# nxapisrv.properties : seul réglage nécessaire pour que le .war déployé par
# Tomcat (voir Dockerfile) trouve le serveur NetXMS. Les deux tournent dans
# le même conteneur, donc 127.0.0.1.
write_websvc_properties() {
  local properties_dir
  # Emplacement attendu par nxapisrv (classpath de l'application) : à défaut
  # de confirmation, on le pose aussi à la racine de Tomcat, qui le trouve
  # généralement en premier sur son CLASSPATH par défaut.
  properties_dir=/usr/share/tomcat9/lib
  mkdir -p "$properties_dir"
  cat > "$properties_dir/nxapisrv.properties" <<PROPS
netxms.server.address=127.0.0.1
netxms.server.port=${NETXMS_SERVER_PORT:-4701}
PROPS
  log "nxapisrv.properties écrit (serveur 127.0.0.1:${NETXMS_SERVER_PORT:-4701})"
}

start_tomcat() {
  write_websvc_properties
  # `catalina.sh run` reste au premier plan : on le passe en tâche de fond
  # pour que netxmsd reste le processus principal du conteneur (repris par
  # `exec` en fin de script), et on journalise sa sortie dans le journal du
  # conteneur plutôt que dans un fichier perdu au redémarrage.
  /usr/share/tomcat9/bin/catalina.sh run > /var/log/tomcat9-websvc.log 2>&1 &
  log "Tomcat démarré (API Legacy Web, port 8080) — journal : /var/log/tomcat9-websvc.log"
}

# ─────────────────────────── compte admin ───────────────────────────
# Un netxmsd neuf crée le compte « admin » avec un mot de passe VIDE : c'est
# le comportement documenté de nxdbmgr init, pas un oubli. Le changer
# automatiquement demanderait une commande nxadm dont la syntaxe n'a pas pu
# être confirmée ici (voir Dockerfile) — plutôt que de deviner et échouer en
# silence, ce script laisse le mot de passe vide et le signale clairement :
# le changer à la main (interface web du .war, ou `nxadm`) avant d'ouvrir ce
# laboratoire à qui que ce soit d'autre que vous.
warn_default_password() {
  if schema_initialized; then
    return 0
  fi
  log "ATTENTION : compte « admin » créé avec un mot de passe VIDE (comportement"
  log "  par défaut de NetXMS). Le changer avant tout accès partagé à ce"
  log "  laboratoire — interface web du .war déployé, ou nxadm en console."
}

# ─────────────────────────── main ───────────────────────────
write_config
wait_for_db

FRESH_INSTALL=1
schema_initialized && FRESH_INSTALL=0

init_schema
[ "$FRESH_INSTALL" = "1" ] && warn_default_password

start_tomcat

log "NetXMS opérationnel — netxmsd au premier plan, API Legacy Web sur le port 8080 (/netxms-websvc)"
exec "$@"
