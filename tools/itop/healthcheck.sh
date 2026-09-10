#!/bin/bash
# Sain = l'API REST répond à l'appel exact que fait le collecteur du NOC.
#
# Vérifier la page d'accueil ne prouverait rien : pendant toute la durée de
# l'installation, Apache sert déjà des 200 sur /. Ce qui compte est que
# /webservices/rest.php authentifie et réponde `"code":0`.
set -euo pipefail

USER=${ITOP_REST_USER:-noc_collector}
PASSWORD=${ITOP_REST_PASSWORD:-}

# Repli sur le compte d'administration tant que le compte de service n'a pas
# été créé (ITOP_REST_PASSWORD vide), sinon le conteneur ne serait jamais sain
# sur une installation où l'exploitant n'a pas voulu de compte dédié.
if [ -z "$PASSWORD" ]; then
  USER=${ITOP_ADMIN_USER:-admin}
  PASSWORD=${ITOP_ADMIN_PASSWORD:-Admin!2026}
fi

response=$(curl -fs -m 10 \
  --data-urlencode "auth_user=${USER}" \
  --data-urlencode "auth_pwd=${PASSWORD}" \
  --data-urlencode 'json_data={"operation":"core/check_credentials","user":"'"${USER}"'","password":"'"${PASSWORD}"'"}' \
  'http://127.0.0.1/webservices/rest.php?version=1.3')

# `"code":0` est le code de succès du protocole REST d'iTop. Une erreur
# d'authentification renvoie 1, une opération inconnue 100 : les deux
# répondent HTTP 200, d'où le contrôle sur le corps et non sur le statut.
printf '%s' "$response" | grep -q '"code": *0'
