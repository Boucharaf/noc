#!/bin/bash
# Déclare dans Centreon les machines RÉELLES de la pile locale, supervisées
# par de vraies sondes ICMP et HTTP.
#
# POURQUOI CE SCRIPT VIT DANS LE CONTENEUR CENTREON. Centreon 22.10 n'expose
# pas la création d'hôtes dans son API REST v2 : l'outil supporté pour
# écrire la configuration est CLAPI (/usr/share/centreon/bin/centreon), un
# binaire local. Le conteneur de provisionnement, extérieur, ne peut donc
# pas créer d'hôtes ; ce script le fait depuis l'intérieur.
#
#     docker compose exec centreon /usr/local/bin/provision-lab
#
# Idempotent : un hôte déjà déclaré est laissé tel quel.
set -uo pipefail

ADMIN_PASSWORD=${CENTREON_ADMIN_PASSWORD:-Centreon!2024}
CLAPI=(/usr/share/centreon/bin/centreon -u admin -p "$ADMIN_PASSWORD")

log() { echo "[provision-lab] $*"; }

# Nom;alias;adresse — l'adresse est le nom DNS du service Docker, jamais une
# IP : les adresses de conteneurs changent à chaque recréation, les noms de
# service non.
HOSTS=(
  "noc-backend;Application NOC — API;backend"
  "noc-frontend;Application NOC — interface;frontend"
  "noc-redis;Cache d'état du NOC;redis"
  "noc-postgres;Base des données propres au NOC;postgres"
  "outil-zabbix;Supervision Zabbix;zabbix-web"
  "outil-itop;ITSM iTop;itop"
)

# Le groupe porte la convention « Site/<nom> » que le connecteur lit pour
# déduire la localité (voir integrations/centreon.py::_site_from_groups).
SITE_GROUP="Site/Laboratoire"

ensure_command() {
  # La sonde ICMP livrée avec Centreon. Créée si absente : une installation
  # neuve sans plugin pack n'a aucune commande de contrôle utilisable.
  "${CLAPI[@]}" -o CMD -a show -v 'check_local_ping' 2>/dev/null | grep -q 'check_local_ping' \
    && return 0
  log "création de la commande check_local_ping"
  "${CLAPI[@]}" -o CMD -a add \
    -v 'check_local_ping;check;$USER1$/check_ping -H $HOSTADDRESS$ -w 3000,80% -c 5000,100% -p 3' \
    >/dev/null 2>&1
}

ensure_group() {
  "${CLAPI[@]}" -o HG -a show -v "$SITE_GROUP" 2>/dev/null | grep -q "$SITE_GROUP" && return 0
  log "création du groupe d'hôtes « $SITE_GROUP »"
  "${CLAPI[@]}" -o HG -a add -v "${SITE_GROUP};${SITE_GROUP}" >/dev/null 2>&1
}

ensure_host() {
  local name=$1 alias=$2 address=$3
  if "${CLAPI[@]}" -o HOST -a show -v "$name" 2>/dev/null | grep -q "^[0-9]*;${name};"; then
    log "hôte « $name » déjà déclaré"
    return 0
  fi
  log "création de l'hôte « $name » ($address)"
  # Le dernier champ est le collecteur ; « Central » est le seul de cette
  # installation.
  "${CLAPI[@]}" -o HOST -a add -v "${name};${alias};${address};;Central;${SITE_GROUP}" \
    >/dev/null 2>&1 || { log "ATTENTION : création de « $name » refusée"; return 1; }

  local parameter
  for parameter in "check_command;check_local_ping" "max_check_attempts;3" \
    "check_interval;1" "retry_check_interval;1" "check_period;24x7" \
    "active_checks_enabled;1" "notifications_enabled;0"; do
    "${CLAPI[@]}" -o HOST -a setparam -v "${name};${parameter}" >/dev/null 2>&1
  done
}

apply_configuration() {
  # Sans export, les hôtes créés restent dans la base de configuration et le
  # moteur ne les contrôle jamais : Centreon sépare configuration et
  # exécution, et c'est l'export qui fait le pont.
  log "export de la configuration vers le collecteur Central"
  "${CLAPI[@]}" -a POLLERGENERATE -v 1 >/dev/null 2>&1 \
    && "${CLAPI[@]}" -a CFGMOVE -v 1 >/dev/null 2>&1 \
    && centreon-service restart centengine >/dev/null 2>&1 \
    && log "configuration appliquée, moteur redémarré" \
    || log "ATTENTION : l'export de configuration a échoué — les hôtes ne seront pas contrôlés"

  # CLAPI démarre Symfony en root et laisse un cache que php-fpm ne peut plus
  # réécrire : chaque appel d'API répondrait alors 500. Le cache est jetable.
  rm -rf /var/cache/centreon/symfony
  chown -R centreon:centreon /var/cache/centreon 2>/dev/null || true
}

ensure_command
ensure_group
for entry in "${HOSTS[@]}"; do
  IFS=';' read -r name alias address <<< "$entry"
  ensure_host "$name" "$alias" "$address"
done
apply_configuration
log "terminé."
