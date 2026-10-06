#!/bin/bash
# Déploie iTop dans son volume, attend MariaDB, puis déroule l'installation
# SANS INTERACTION livrée par Combodo au premier démarrage.
#
# Point important : on n'imite pas l'assistant web, on appelle l'installateur
# officiel `web/setup/unattended-install/unattended-install.php` avec un fichier
# de réponses XML — c'est le mode d'installation documenté par l'éditeur pour
# l'automatisation. Le fichier de réponses est généré ici à partir de
# l'environnement, sur le modèle de xml_setup/itil-fresh-install.xml.
#
# `sample_data` vaut 0 : iTop propose d'installer un jeu de données de
# démonstration (organisations, contacts et tickets fictifs de Combodo). On le
# refuse — la CMDB ne doit contenir que des objets réels.
set -euo pipefail

log() { echo "[entrypoint] $*"; }
die() { echo "[entrypoint] ERREUR: $*" >&2; exit 1; }

DB_HOST=${ITOP_DB_HOST:-itop-db}
DB_PORT=${ITOP_DB_PORT:-3306}
DB_NAME=${ITOP_DB_NAME:-itop}
DB_USER=${ITOP_DB_USER:-itop}
DB_PASSWORD=${ITOP_DB_PASSWORD:-itop}
DB_PREFIX=${ITOP_DB_PREFIX:-}

ADMIN_USER=${ITOP_ADMIN_USER:-admin}
ADMIN_PASSWORD=${ITOP_ADMIN_PASSWORD:-Admin!2026}
APP_URL=${ITOP_APP_URL:-http://localhost:8082/}
LANGUAGE=${ITOP_LANGUAGE:-FR FR}
TIMEZONE=${TZ:-Africa/Ouagadougou}

# Compte de service dédié au collecteur du NOC. Interroger l'API avec le compte
# d'administration marcherait, mais laisserait le NOC capable de TOUT modifier
# dans l'ITSM ; ce compte-ci ne porte que le profil « REST Services User ».
REST_USER=${ITOP_REST_USER:-noc_collector}
REST_PASSWORD=${ITOP_REST_PASSWORD:-}

SRC=${ITOP_SRC:-/usr/src/itop-src/web}
HOME_DIR=${ITOP_HOME:-/var/www/html}
CONFIG_FILE="$HOME_DIR/conf/production/config-itop.php"
PARAM_FILE=/tmp/itop-unattended-install.xml
INSTALLATION_XML="$HOME_DIR/datamodels/2.x/installation.xml"

# ─────────────────────────── PHP ───────────────────────────
# Le fuseau est injecté ici et non dans l'image : c'est une donnée
# d'exploitation, elle doit suivre la variable TZ du compose.
configure_php() {
  sed -i "s|^date.timezone = .*|date.timezone = ${TIMEZONE}|" \
    /usr/local/etc/php/conf.d/99-itop.ini
  log "PHP configuré (fuseau ${TIMEZONE})"
}

# ─────────────────────────── déploiement ───────────────────────────
# /var/www/html est un volume : il survit à la reconstruction de l'image. On n'y
# déploie l'application que s'il est vide, sinon une reconstruction écraserait
# la configuration et les extensions installées par l'exploitant.
deploy_application() {
  if [ -f "$HOME_DIR/index.php" ]; then
    log "application déjà déployée dans ${HOME_DIR} — déploiement ignoré"
    return 0
  fi
  log "déploiement d'iTop dans ${HOME_DIR}…"
  cp -a "$SRC/." "$HOME_DIR/"
  log "iTop déployé"
}

# iTop écrit dans conf/, data/, log/ et env-production/ pendant et après
# l'installation. Le volume garde les uid/gid avec lesquels il a été peuplé :
# on réaffirme le propriétaire par NOM à chaque démarrage.
fix_ownership() {
  chown -R www-data:www-data "$HOME_DIR"
  log "propriétaire de ${HOME_DIR} vérifié (www-data)"
}

# ─────────────────────────── base de données ───────────────────────────
wait_for_db() {
  log "attente de ${DB_HOST}:${DB_PORT}…"
  for _ in $(seq 1 90); do
    if mariadb -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" "-p$DB_PASSWORD" \
        -e 'SELECT 1' >/dev/null 2>&1; then
      log "base de données joignable"
      return 0
    fi
    sleep 2
  done
  die "${DB_HOST}:${DB_PORT} injoignable (ou identifiants erronés) après 180 s"
}

# ─────────────────────────── installation ───────────────────────────
# Le fichier de réponses reprend la structure de
# web/setup/unattended-install/xml_setup/itil-fresh-install.xml : la liste
# `selected_extensions` est celle du profil ITIL complet, et c'est
# installation.xml (passé en --installation_xml) qui en déduit les modules.
#
# Ce périmètre est exactement celui dont le NOC a besoin :
#   itop-config-mgmt-*        -> Organization, Location, Server, NetworkDevice
#   itop-ticket-mgmt-itil-*   -> Incident et UserRequest
#   itop-service-mgmt-*       -> SLA/SLT, lus pour le calcul du respect des délais
write_param_file() {
  cat > "$PARAM_FILE" <<XML
<?xml version="1.0" encoding="UTF-8"?>
<installation>
  <mode>install</mode>
  <preinstall></preinstall>
  <source_dir>datamodels/2.x/</source_dir>
  <datamodel_version>${ITOP_DATAMODEL_VERSION:-3.2.0}</datamodel_version>
  <previous_configuration_file>${CONFIG_FILE}</previous_configuration_file>
  <extensions_dir>extensions</extensions_dir>
  <target_env>production</target_env>
  <workspace_dir></workspace_dir>
  <database>
    <server>${DB_HOST}:${DB_PORT}</server>
    <user>${DB_USER}</user>
    <pwd>${DB_PASSWORD}</pwd>
    <name>${DB_NAME}</name>
    <db_tls_enabled></db_tls_enabled>
    <db_tls_ca></db_tls_ca>
    <prefix>${DB_PREFIX}</prefix>
  </database>
  <url>${APP_URL}</url>
  <graphviz_path>/usr/bin/dot</graphviz_path>
  <admin_account>
    <user>${ADMIN_USER}</user>
    <pwd>${ADMIN_PASSWORD}</pwd>
    <language>${LANGUAGE}</language>
  </admin_account>
  <language>${LANGUAGE}</language>
  <sample_data>0</sample_data>
  <old_addon></old_addon>
  <options type="array"/>
  <mysql_bindir></mysql_bindir>
  <selected_modules type="array"></selected_modules>
  <selected_extensions type="array">
    <item>itop-config-mgmt-core</item>
    <item>itop-config-mgmt-datacenter</item>
    <item>itop-config-mgmt-end-user</item>
    <item>itop-config-mgmt-storage</item>
    <item>itop-config-mgmt-virtualization</item>
    <item>itop-service-mgmt-enterprise</item>
    <item>itop-ticket-mgmt-itil</item>
    <item>itop-ticket-mgmt-itil-user-request</item>
    <item>itop-ticket-mgmt-itil-incident</item>
    <item>itop-ticket-mgmt-itil-enhanced-portal</item>
    <item>itop-change-mgmt-itil</item>
    <item>itop-kown-error-mgmt</item>
  </selected_extensions>
</installation>
XML
  chown www-data:www-data "$PARAM_FILE"
}

run_install() {
  log "pas de ${CONFIG_FILE} — installation sans interaction d'iTop"
  write_param_file
  [ -f "$INSTALLATION_XML" ] || die "installation.xml introuvable : ${INSTALLATION_XML}"

  # Exécuté sous www-data, comme le recommande la documentation : tout ce que
  # l'installation crée doit rester accessible en écriture au serveur web.
  if ! runuser -u www-data -- php \
      "$HOME_DIR/setup/unattended-install/unattended-install.php" \
      --param-file="$PARAM_FILE" \
      --installation_xml="$INSTALLATION_XML" 2>&1 | sed 's/^/[setup] /'; then
    die "l'installation iTop a échoué — voir les lignes [setup] ci-dessus et ${HOME_DIR}/log/setup.log"
  fi

  [ -f "$CONFIG_FILE" ] || die "l'installation s'est terminée sans écrire ${CONFIG_FILE}"
  log "iTop installé"
}

# Le compte de service du collecteur : UserLocal + profil « REST Services User ».
# Créé via l'ORM d'iTop plutôt que par des INSERT SQL, pour que les règles du
# modèle (hash du mot de passe, contact lié, historique) s'appliquent.
#
# Au pire un avertissement : le collecteur sait retomber sur le compte
# d'administration, et l'exploitant peut créer ce compte dans l'interface.
create_rest_user() {
  [ -n "$REST_PASSWORD" ] || { log "ITOP_REST_PASSWORD vide — compte de service non créé"; return 0; }
  local script=${ITOP_REST_USER_SCRIPT:-/usr/local/share/itop/create-rest-user.php}
  [ -f "$script" ] || { log "ATTENTION : ${script} introuvable — compte de service non créé"; return 0; }
  runuser -u www-data -- php "$script" "$REST_USER" "$REST_PASSWORD" 2>&1 \
      | sed 's/^/[rest-user] /' \
    || log "ATTENTION : le compte de service « ${REST_USER} » n'a pas pu être créé ; le collecteur retombera sur le compte d'administration"
}

# ─────────────────────────── tâches de fond ───────────────────────────
# iTop confie à cron.php ses traitements différés : calcul des échéances SLA,
# notifications, purge des sessions. Sans lui, un ticket ne franchit jamais ses
# jalons de temps et les délais lus par le NOC restent figés.
start_cron() {
  [ "${ITOP_CRON_ENABLED:-true}" = "true" ] || { log "ITOP_CRON_ENABLED=false — tâches de fond désactivées"; return 0; }
  (
    while true; do
      runuser -u www-data -- php "$HOME_DIR/webservices/cron.php" \
        --auth_user="$ADMIN_USER" --auth_pwd="$ADMIN_PASSWORD" --param_file= \
        >> /var/log/itop-cron.log 2>&1 || true
      sleep "${ITOP_CRON_INTERVAL_S:-60}"
    done
  ) &
  log "tâches de fond démarrées (cron.php toutes les ${ITOP_CRON_INTERVAL_S:-60} s)"
}

# ─────────────────────────── main ───────────────────────────
configure_php
deploy_application
fix_ownership
wait_for_db

if [ ! -f "$CONFIG_FILE" ]; then
  run_install
  fix_ownership
else
  log "${CONFIG_FILE} présent — installation ignorée"
fi

# À CHAQUE démarrage, et non seulement à l'installation. Le script est
# idempotent : il crée le compte s'il manque, et se contente d'AJOUTER les
# profils absents s'il existe. Le faire à chaque fois garantit qu'un profil
# ajouté à la liste après coup finit par être appliqué — sinon il faudrait
# réinstaller iTop de zéro pour corriger une habilitation.
create_rest_user

start_cron

log "iTop opérationnel — interface et API REST sur le port 80"
exec "$@"
