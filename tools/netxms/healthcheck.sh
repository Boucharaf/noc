#!/bin/bash
# Sain = l'API Legacy Web (Tomcat + netxms-websvc.war) répond ET peut se
# connecter à netxmsd. Un Tomcat démarré ne suffit pas : au premier
# démarrage, nxdbmgr init peut tourner plusieurs minutes pendant lesquelles
# Tomcat répond déjà mais netxmsd n'écoute pas encore.
#
# ⚠️ Le chemin exact (`/netxms-websvc/`) suppose que le .war se déploie sous
# le nom de son fichier (comportement par défaut de Tomcat pour un fichier
# nommé netxms-websvc.war — voir Dockerfile). Si le healthcheck reste rouge
# alors que les journaux ne montrent aucune erreur, vérifier le contexte
# réellement déployé : docker compose exec netxms-server ls
# /var/lib/tomcat9/webapps/
set -euo pipefail

curl -fs -m 10 'http://127.0.0.1:8080/netxms-websvc/' | grep -q '"version"'
