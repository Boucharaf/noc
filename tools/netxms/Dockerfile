# NetXMS 5.0.8 — serveur (netxmsd) + API Legacy Web (netxms-websvc), pour le
# laboratoire local. Même logique que tools/centreon et tools/itop : une
# installation NEUVE de la version exacte exploitée par l'agence, jamais une
# restauration de données de production.
#
# POURQUOI UNE INSTALLATION NEUVE ET NON LE DUMP DE PRODUCTION. Le dump
# restauré dans le service `netxms-db` (voir docker-compose.yml et
# database/restore_netxms_dump.sh) reste un instantané réel de
# l'infrastructure de l'agence : il ne doit voyager nulle part hors du poste
# où il a été restauré, encore moins vers une VM de préproduction partagée.
# Un `netxmsd` neuf, sans les canaux de notification ni les communautés SNMP
# réelles de la production, peut tourner sans danger — c'est précisément
# l'absence de ces éléments qui rendait dangereux de démarrer un serveur sur
# le dump. Ce conteneur active donc le même chemin de code que la production
# EMPRUNTERA le jour où l'agence ouvrira l'accès API : integrations/netxms.py
# (API Legacy Web), pas integrations/netxms_db.py (lecture directe de base).
#
# NetXMS ne publie pas d'image Docker officielle. Cette image installe les
# paquets Debian de l'éditeur depuis packages.netxms.org, comme le ferait une
# installation manuelle suivant la documentation officielle, puis déploie
# l'API Legacy Web (un .war Java autonome, PAS empaqueté par l'éditeur — voir
# la note plus bas) dans un Tomcat.
#
# ⚠️ DEUX POINTS NON VÉRIFIÉS CONTRE UNE VRAIE INSTANCE, À CONFIRMER AU
#    PREMIER BUILD (le reste de cette image repose sur la documentation
#    officielle et des rapports d'utilisateurs confirmés) :
#
#    1. Le découpage exact des paquets Debian pour la 5.0 (metapaquet unique
#       `netxms-server` ou pilote de base séparé `netxms-server-pgsql` /
#       `netxms-dbdrv-pgsql`). Si `apt-get install` échoue sur un paquet
#       introuvable, lister ce qui existe réellement :
#           docker compose run --rm netxms-server bash -c \
#             'apt-get update && apt-cache search netxms'
#       et ajuster la liste ci-dessous en conséquence.
#
#    2. L'URL exacte du .war de l'API. Le nom de fichier et le chemin
#       `/download/releases/5.0/…` sont confirmés pour `nxmc-5.0.8.war` (le
#       Web Console, PAS l'API) par un rapport d'utilisateur qui tourne
#       exactement en 5.0.8 ; le fichier de l'API suit la même convention de
#       nommage (`netxms-websvc-5.0.8.war`) mais n'a pas été téléchargé pour
#       vérification ici. Si le `curl` plus bas échoue en 404, la page
#       https://netxms.com/downloads/ liste les binaires de la version 5.0
#       sous « Integration Tools » — copier l'URL exacte trouvée là.
FROM debian:bookworm-slim

ARG NETXMS_VERSION=5.0.8
ARG NETXMS_WEBSVC_URL=https://netxms.com/download/releases/5.0/netxms-websvc-5.0.8.war

# Instantané Debian : même raisonnement que tools/centreon/Dockerfile et
# tools/itop/Dockerfile — une construction reproductible dans deux ans, même
# si bookworm venait à son tour en fin de vie entre-temps.
ARG DEBIAN_SNAPSHOT=20260901T000000Z

ENV DEBIAN_FRONTEND=noninteractive

RUN set -eux; \
    printf '%s\n' \
        "deb http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}/ bookworm main" \
        "deb http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}/ bookworm-updates main" \
        "deb http://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT}/ bookworm-security main" \
        > /etc/apt/sources.list; \
    printf '%s\n' \
        'Acquire::Check-Valid-Until "false";' \
        'Acquire::Retries "5";' \
        'Acquire::http::Timeout "120";' \
        > /etc/apt/apt.conf.d/99snapshot; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg procps postgresql-client \
        openjdk-17-jre-headless tomcat9 \
    ; \
    rm -rf /var/lib/apt/lists/*

# Dépôt officiel de l'éditeur : le paquet `netxms-release-latest.deb`
# installe à la fois la clé de signature et la liste de dépôt pour la
# distribution détectée (bookworm ici). Après quoi le dépôt se comporte comme
# n'importe quel autre — d'où l'épinglage explicite par version juste après,
# sur le même principe que CENTREON_VERSION dans tools/centreon/Dockerfile.
RUN set -eux; \
    curl -fsSLO https://packages.netxms.org/netxms-release-latest.deb; \
    dpkg -i netxms-release-latest.deb; \
    rm netxms-release-latest.deb; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        "netxms-server=${NETXMS_VERSION}*" \
    ; \
    rm -rf /var/lib/apt/lists/*

# API Legacy Web : un .war Java autonome, distribué en dehors du système de
# paquets (voir la note en tête de fichier) — téléchargé à la CONSTRUCTION
# pour qu'aucun démarrage de conteneur n'ait besoin d'Internet. Tomcat
# l'auto-déploie au démarrage depuis son répertoire webapps.
RUN set -eux; \
    curl -fsSL -o /var/lib/tomcat9/webapps/netxms-websvc.war "${NETXMS_WEBSVC_URL}"; \
    test -s /var/lib/tomcat9/webapps/netxms-websvc.war

# nxapisrv.properties : seul réglage nécessaire est l'adresse du serveur
# NetXMS, réécrit par l'entrypoint à partir de NETXMS_SERVER_HOST — ici les
# deux tournent dans le même conteneur, donc 127.0.0.1 par défaut.
RUN mkdir -p /usr/share/tomcat9/lib

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY healthcheck.sh /usr/local/bin/healthcheck.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh /usr/local/bin/healthcheck.sh

EXPOSE 8080

# Sain = l'API Legacy Web répond, ET netxmsd accepte une authentification —
# un Tomcat démarré ne prouve rien si netxmsd derrière n'a pas fini de
# s'initialiser (nxdbmgr init peut prendre plusieurs minutes au premier
# démarrage).
HEALTHCHECK --interval=30s --timeout=15s --start-period=300s --retries=10 \
    CMD /usr/local/bin/healthcheck.sh

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["netxmsd", "-D0"]
