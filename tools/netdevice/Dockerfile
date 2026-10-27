# Équipement réseau de laboratoire — un « routeur » minimal.
#
# Le laboratoire n'a pas de vrais routeurs : sans eux, Zabbix et Centreon
# n'ont aucune interface, aucun débit, aucune latence à remonter, et les
# panneaux réseau du NOC restent vides. Chaque conteneur de cette image
# tient le rôle d'un équipement de site :
#
#   * un VRAI agent SNMP (net-snmp) : IF-MIB (compteurs d'interface 64 bits),
#     HOST-RESOURCES et UCD (CPU, mémoire, disque), sysName, sysLocation —
#     exactement ce qu'interrogent les gabarits SNMP de Zabbix et les
#     plugins SNMP de Centreon ;
#   * un VRAI trafic, envoyé à un équipement voisin : les compteurs d'octets
#     que lit la supervision augmentent pour de bon ;
#   * les conditions du lien (latence, pertes, coupures), appliquées aux
#     réponses ICMP par icmp_responder.py et aux requêtes SNMP par iptables :
#     le ping des outils mesure lui-même le temps d'aller-retour.
#
# Rien n'est écrit en base des outils : toute valeur affichée a traversé la
# sonde, l'outil, son API et le connecteur du NOC.
#
# ~15 Mo de mémoire par équipement.
FROM alpine:3.20

RUN apk add --no-cache net-snmp socat tini python3 iptables

COPY icmp_responder.py /usr/local/lib/icmp_responder.py
COPY entrypoint.sh /usr/local/bin/netdevice
RUN chmod +x /usr/local/bin/netdevice

EXPOSE 161/udp
ENTRYPOINT ["/sbin/tini", "--", "/usr/local/bin/netdevice"]
