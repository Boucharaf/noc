# Centreon central 22.10 (interface web + API REST v2 + engine + broker +
# gorgone) — la version que l'agence exploite en production.
#
# Centreon ne publie aucune image Docker supportée. Cette image installe les
# paquets Debian de l'éditeur depuis packages.centreon.com, exactement comme
# le ferait une installation manuelle en suivant la documentation officielle.
#
# Trois dépôts sont nécessaires, et l'ordre compte :
#   1. sury      — Debian 11 livre PHP 7.4, or centreon-web 22.10 dépend de
#                  php8.1-* ; sans ce dépôt, apt ne résout pas la dépendance ;
#   2. centreon  — la branche 22.10 stable pour bullseye ;
#   3. plugins   — les sondes de supervision (check_centreon_*).
#
# La base de données vit dans un conteneur séparé (centreon-db, MariaDB 10.5) :
# Centreon crée lui-même ses deux schémas (centreon, centreon_storage) pendant
# l'installation pilotée par l'entrypoint.
FROM debian:bullseye-slim

# Version épinglée au correctif près. `docker compose build --build-arg
# CENTREON_VERSION=22.10.31` suffit à suivre l'agence si elle met à jour.
ARG CENTREON_BRANCH=22.10
ARG CENTREON_VERSION=22.10.7
ARG CENTREON_SUITE=bullseye

# Instantané Debian sur lequel l'image est bâtie. Le figer rend la
# construction reproductible ; le faire avancer ne demande que de changer
# cette date : `docker compose build --build-arg DEBIAN_SNAPSHOT=…`.
ARG DEBIAN_SNAPSHOT=20260901T000000Z

ENV DEBIAN_FRONTEND=noninteractive

# curl et mariadb-client restent dans l'image : l'entrypoint pilote l'assistant
# d'installation en HTTP avec curl, attend la base avec mariadb-client, et le
# healthcheck appelle l'API REST avec curl.
# Debian 11 est en fin de vie et ses miroirs courants sont en cours de vidage :
# le fichier Release de bullseye-security a expiré (apt refuse alors le dépôt en
# bloc) et son pool perd ses paquets au fil des jours — les 404 changent d'un
# jour à l'autre. Une image qui se construit aujourd'hui et plus demain n'a
# aucune valeur pour reproduire la production.
#
# On bâtit donc sur snapshot.debian.org, l'archive horodatée que Debian
# conserve indéfiniment : à instantané fixé, cette image se reconstruit à
# l'identique dans deux ans. C'est la méthode recommandée par Debian pour
# les distributions en fin de vie.
#
# Le dépôt de sécurité ne peut pas être simplement retiré : l'image de base en
# embarque déjà des paquets (perl-base, gpgv, libexpat1), et sans lui apt
# tenterait de les rétrograder — « held broken packages ».
#
# La vérification de SIGNATURE reste active : seule la date de péremption de
# l'index est ignorée, les paquets restent authentifiés par la clé Debian.
RUN set -eux; \
    printf '%s\n' \
        "deb http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}/ bullseye main" \
        "deb http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}/ bullseye-updates main" \
        "deb http://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT}/ bullseye-security main" \
        > /etc/apt/sources.list; \
    printf '%s\n' \
        'Acquire::Check-Valid-Until "false";' \
        'Acquire::Retries "5";' \
        'Acquire::http::Timeout "120";' \
        > /etc/apt/apt.conf.d/99snapshot; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg lsb-release procps mariadb-client; \
    install -d /etc/apt/keyrings; \
    \
    curl -fsSL https://packages.sury.org/php/apt.gpg \
        | gpg --dearmor -o /etc/apt/keyrings/sury-php.gpg; \
    echo "deb [signed-by=/etc/apt/keyrings/sury-php.gpg] https://packages.sury.org/php/ ${CENTREON_SUITE} main" \
        > /etc/apt/sources.list.d/sury-php.list; \
    \
    curl -fsSL https://apt-key.centreon.com \
        | gpg --dearmor -o /etc/apt/keyrings/centreon.gpg; \
    echo "deb [signed-by=/etc/apt/keyrings/centreon.gpg] https://packages.centreon.com/apt-standard-${CENTREON_BRANCH}-stable/ ${CENTREON_SUITE} main" \
        > /etc/apt/sources.list.d/centreon.list; \
    echo "deb [signed-by=/etc/apt/keyrings/centreon.gpg] https://packages.centreon.com/apt-plugins-stable/ ${CENTREON_SUITE} main" \
        > /etc/apt/sources.list.d/centreon-plugins.list; \
    \
    apt-get update; \
    \
    # ÉPINGLAGE DE VERSION — et pourquoi il ne porte QUE sur l'interface web.
    #
    # La branche 22.10 versionne chaque composant indépendamment : au moment
    # d'écrire ces lignes, le dépôt propose centreon-web 22.10.31,
    # centreon-broker 22.10.12 et centreon-gorgone 22.10.9. Le « 22.10.7 »
    # que rapporte l'agence est donc la version de centreon-web — celle
    # qu'affiche Administration > À propos et que rend /platform/versions.
    #
    # Épingler le seul métapaquet centreon-central ne suffit pas : apt résout
    # ses dépendances au plus récent et installe un web 22.10.31.
    #
    # Mais on ne peut pas non plus tout épingler à 22.10.7 : centreon-engine
    # (dont le dépôt n'offre que 22.10.12) exige centreon-common >= 22.10.12,
    # et exiger centreon-common=22.10.7 rend l'ensemble insoluble —
    # « held broken packages ». Les paquets du moteur et du broker ont leur
    # propre cadence de correctifs, et l'éditeur ne publie pas de jeu
    # cohérent daté.
    #
    # On épingle donc exactement ce qui porte l'identité de la version, et
    # rien de plus. Les composants d'exécution restent au dernier correctif
    # de la branche 22.10 — ce qui est de toute façon la configuration d'une
    # plateforme maintenue.
    #
    # Une strophe apt n'admet qu'UNE ligne « Package: » ; les paquets s'y
    # listent séparés par des espaces. Priorité 1001 et non 990 : au-delà de
    # 1000, apt s'autorise à RÉTROGRADER, ce qu'il faut ici puisque le dépôt
    # propose des versions plus récentes que celle qu'on exige.
    printf '%s\n' \
        'Package: centreon-central centreon-web centreon-web-apache centreon-web-common' \
        "Pin: version ${CENTREON_VERSION}-${CENTREON_SUITE}" \
        'Pin-Priority: 1001' \
        > /etc/apt/preferences.d/centreon-version; \
    \
    apt-get install -y \
        "centreon-central=${CENTREON_VERSION}-${CENTREON_SUITE}" \
        "centreon-web=${CENTREON_VERSION}-${CENTREON_SUITE}" \
        "centreon-web-common=${CENTREON_VERSION}-${CENTREON_SUITE}" \
        "centreon-web-apache=${CENTREON_VERSION}-${CENTREON_SUITE}" \
        ; \
    \
    # gorgoned (l'ordonnanceur qui relaie les ordres du central vers les
    # collecteurs) dépend de Hash::Merge, qui dépend lui-même de
    # Clone::Choose — que le paquet centreon-gorgone 22.10 NE DÉCLARE PAS.
    # Sans lui, le démon meurt au démarrage sur « Can't locate
    # Clone/Choose.pm » et l'export de configuration depuis l'interface
    # échoue silencieusement. C'est un défaut d'empaquetage de l'éditeur,
    # comblé ici.
    apt-get install -y --no-install-recommends libclone-choose-perl; \
    apt-get purge -y gnupg; \
    apt-get autoremove -y; \
    rm -rf /var/lib/apt/lists/*

# Apache ne doit servir PHP QUE par le pool php-fpm de Centreon. Le mod_php
# tiré par le métapaquet php8.1 serait un second PHP non configuré, et il
# impose le MPM prefork.
RUN set -eux; \
    a2dismod php8.1 mpm_prefork 2>/dev/null || true; \
    a2enmod mpm_event proxy_fcgi rewrite headers setenvif

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY healthcheck.sh /usr/local/bin/healthcheck.sh
COPY centreon-service.sh /usr/local/bin/centreon-service
COPY provision-lab.sh /usr/local/bin/provision-lab
RUN set -eux; \
    chmod +x /usr/local/bin/docker-entrypoint.sh /usr/local/bin/healthcheck.sh \
        /usr/local/bin/centreon-service /usr/local/bin/provision-lab; \
    # Centreon relance ses démons par `sudo systemctl restart …` (voir
    # /etc/sudoers.d/centreon), et sudo compare la règle au CHEMIN du binaire :
    # il faut donc prendre la place de systemctl, pas seulement le masquer
    # dans le PATH.
    dpkg-divert --local --rename --add /usr/bin/systemctl; \
    ln -s /usr/local/bin/centreon-service /usr/bin/systemctl

# 80 interface web + API REST v2 · 5669 gorgone ZMQ (collecteurs distants)
EXPOSE 80 5669

# L'assistant d'installation tourne au premier démarrage et prend plusieurs
# minutes sur une base froide, d'où la longue période de grâce.
HEALTHCHECK --interval=30s --timeout=10s --start-period=600s --retries=10 \
    CMD /usr/local/bin/healthcheck.sh

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["centreon"]
