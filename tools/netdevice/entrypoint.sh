#!/bin/sh
# Équipement réseau de laboratoire : agent SNMP, trafic, conditions de lien.
#
# Variables :
#   DEVICE_NAME        sysName rendu en SNMP
#   DEVICE_LOCATION    sysLocation
#   SNMP_COMMUNITY     communauté SNMPv2c en lecture (défaut : public)
#   PEER               équipement vers lequel envoyer du trafic (nom DNS)
#   TRAFFIC_KBPS       débit moyen émis vers PEER, en kbit/s (0 = aucun)
#   DELAY_MS           latence du lien (réponses ICMP)
#   JITTER_MS          gigue
#   LOSS_PCT           pertes de paquets (%) — ICMP et SNMP
#   OUTAGE_EVERY_MIN   période des coupures simulées (0 = jamais)
#   OUTAGE_FOR_MIN     durée de chaque coupure
#
# Une coupure rend l'équipement muet : plus de réponse au ping ni au SNMP,
# exactement comme un lien tombé. La supervision lève une vraie alerte,
# puis la résout au retour du lien.
#
# Le noyau ne doit pas répondre lui-même au ping (sysctl
# net.ipv4.icmp_echo_ignore_all=1, posé par docker-compose) : c'est
# icmp_responder.py qui le fait, avec la latence du lien.
set -eu

NAME=${DEVICE_NAME:-$(hostname)}
LOCATION=${DEVICE_LOCATION:-Laboratoire}
COMMUNITY=${SNMP_COMMUNITY:-public}
TRAFFIC_KBPS=${TRAFFIC_KBPS:-0}
LOSS_PCT=${LOSS_PCT:-0}
OUTAGE_EVERY_MIN=${OUTAGE_EVERY_MIN:-0}
OUTAGE_FOR_MIN=${OUTAGE_FOR_MIN:-5}
OUTAGE_FLAG=/run/outage
export OUTAGE_FLAG

log() { echo "[$NAME] $*"; }

cat > /etc/snmp/snmpd.conf <<EOF
agentAddress udp:161
rocommunity $COMMUNITY default
sysName $NAME
sysLocation $LOCATION
sysContact noc-lab@resina.local
sysServices 76
# Disque racine pour HOST-RESOURCES (hrStorage) et UCD (dskTable).
disk / 10000
EOF

# ── Pertes SNMP ───────────────────────────────────────────────────────
rm -f "$OUTAGE_FLAG"
if [ "$LOSS_PCT" != "0" ]; then
  probability=$(awk "BEGIN { printf \"%.4f\", $LOSS_PCT / 100 }")
  iptables -A INPUT -p udp --dport 161 -m statistic --mode random \
    --probability "$probability" -j DROP 2>/dev/null \
    || log "ATTENTION : iptables indisponible (cap NET_ADMIN ?) — SNMP sans pertes"
fi

if [ "$(cat /proc/sys/net/ipv4/icmp_echo_ignore_all 2>/dev/null)" != "1" ]; then
  log "ATTENTION : le noyau répond encore au ping — latence non appliquée" \
      "(sysctl net.ipv4.icmp_echo_ignore_all=1 absent)"
fi
python3 /usr/local/lib/icmp_responder.py &

# ── Coupures périodiques ──────────────────────────────────────────────
if [ "$OUTAGE_EVERY_MIN" != "0" ]; then
  (
    while :; do
      sleep $(( (OUTAGE_EVERY_MIN - OUTAGE_FOR_MIN) * 60 ))
      log "coupure du lien pour ${OUTAGE_FOR_MIN} min"
      touch "$OUTAGE_FLAG"
      iptables -I INPUT 1 -p udp --dport 161 -j DROP 2>/dev/null || true
      sleep $(( OUTAGE_FOR_MIN * 60 ))
      log "lien rétabli"
      iptables -D INPUT -p udp --dport 161 -j DROP 2>/dev/null || true
      rm -f "$OUTAGE_FLAG"
    done
  ) &
fi

# ── Service discard (9/udp) ───────────────────────────────────────────
# Reçoit et jette le trafic des voisins. Sans écoute, le noyau répond
# « port inaccessible » au premier datagramme et l'émetteur (socat) s'arrête
# aussitôt : les compteurs ne voient passer que quelques kilo-octets.
socat -u UDP-RECV:9,reuseaddr /dev/null &

# ── Trafic ────────────────────────────────────────────────────────────
# Rafales d'une seconde vers le port discard (9/udp) du voisin. Le débit
# varie au fil de la journée et d'une seconde à l'autre, comme un vrai lien
# — sans quoi les courbes seraient des droites. Le contenu (des zéros)
# n'a pas d'importance : seuls les octets comptent. Interrompu pendant une
# coupure : un lien tombé ne transporte rien.
if [ -n "${PEER:-}" ] && [ "$TRAFFIC_KBPS" != "0" ]; then
  (
    while :; do
      if [ ! -e "$OUTAGE_FLAG" ]; then
        hour=$(date +%H | sed 's/^0//')
        # Heures ouvrées (8 h - 18 h) : charge pleine ; la nuit : un quart.
        if [ "${hour:-0}" -ge 8 ] && [ "${hour:-0}" -lt 18 ]; then load=100; else load=25; fi
        # Variation aléatoire de ±40 % autour de la charge horaire.
        jitter=$(( $(od -An -N1 -tu1 /dev/urandom) * 80 / 255 + 60 ))
        bytes=$(( TRAFFIC_KBPS * 125 * load / 100 * jitter / 100 ))
        head -c "$bytes" /dev/zero | socat -u -b 1400 - "UDP:${PEER}:9" 2>/dev/null || true
      fi
      sleep 1
    done
  ) &
  log "trafic : ~${TRAFFIC_KBPS} kbit/s vers $PEER"
fi

log "agent SNMP v2c (communauté « $COMMUNITY ») sur udp/161"
exec snmpd -f -Lo -C -c /etc/snmp/snmpd.conf
