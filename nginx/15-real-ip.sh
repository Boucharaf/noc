#!/bin/sh
# Adresse réelle des postes derrière un proxy frontal (NOC_FRONT_PROXY_IPS).
#
# Sans cela, tous les postes ont l'adresse du proxy : le journal d'audit ne
# les distingue plus, et les échecs de connexion de l'un bloquent les autres.
# Vide (défaut) : X-Forwarded-For est ignoré, car n'importe quel client peut
# l'écrire. N'y mettre QUE l'adresse du proxy, jamais un réseau de postes.
set -eu
out=/etc/nginx/real-ip.conf
: > "$out"
for item in $(echo "${NOC_FRONT_PROXY_IPS:-}" | tr ',' ' '); do
    if ! echo "$item" | grep -Eq '^[0-9a-fA-F.:]+(/[0-9]{1,3})?$'; then
        echo "NOC_FRONT_PROXY_IPS : valeur refusée « $item »" >&2
        exit 1
    fi
    case "$item" in
        */0) echo "NOC_FRONT_PROXY_IPS : « $item » accepterait tout le monde" >&2; exit 1 ;;
    esac
    echo "set_real_ip_from $item;" >> "$out"
done
if [ -s "$out" ]; then
    echo "real_ip_header X-Forwarded-For;" >> "$out"
    echo "real_ip_recursive on;" >> "$out"
fi
