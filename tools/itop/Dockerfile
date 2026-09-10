# iTop 3.2.3-2 (build 20678) — la version exacte que l'agence exploite.
#
# Aucune image officielle Combodo n'existe, et les images communautaires
# s'arrêtent à 3.2.2. Celle-ci part de l'image PHP officielle et déploie
# l'archive publiée par Combodo sur GitHub.
#
# La base MariaDB vit dans un conteneur séparé (itop-db) : les images
# communautaires embarquent leur MySQL, ce qui interdit de sauvegarder ou de
# redimensionner la base indépendamment de l'application.
#
# L'installation est déroulée par l'installateur SANS INTERACTION livré par
# Combodo (web/setup/unattended-install/unattended-install.php), et non par un
# script maison qui simulerait l'assistant web. Voir docker-entrypoint.sh.
FROM php:8.1-apache-bullseye

ARG ITOP_VERSION=3.2.3-2
ARG ITOP_BUILD=20678

# Instantané Debian sur lequel l'image est bâtie — voir le commentaire du
# premier RUN. Le figer rend la construction reproductible.
ARG DEBIAN_SNAPSHOT=20260901T000000Z

ENV DEBIAN_FRONTEND=noninteractive

# Debian 11 est en fin de vie et ses miroirs courants sont en cours de vidage :
# le fichier Release de bullseye-security a expiré (apt refuse alors le dépôt en
# bloc) et son pool perd ses paquets au fil des jours. On bâtit donc sur
# snapshot.debian.org, l'archive horodatée que Debian conserve indéfiniment :
# à instantané fixé, cette image se reconstruit à l'identique dans deux ans.
#
# Le dépôt de sécurité ne peut pas être simplement retiré : l'image de base en
# embarque déjà des paquets, et sans lui apt tenterait de les rétrograder.
# La vérification de SIGNATURE reste active — seule la date de péremption de
# l'index est ignorée.
#
# Dépendances iTop (documentation officielle « Installation prerequisites ») :
#   graphviz       — obligatoire, iTop refuse de s'installer sans /usr/bin/dot
#                    (rendu des vues d'impact de la CMDB) ;
#   mariadb-client — mysqldump, utilisé par le module de sauvegarde d'iTop, et
#                    par l'entrypoint pour attendre que la base réponde ;
#   lib*-dev       — sources des extensions PHP compilées à l'étape suivante.
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
        graphviz \
        mariadb-client \
        unzip \
        libzip-dev \
        libpng-dev \
        libjpeg62-turbo-dev \
        libfreetype6-dev \
        libxml2-dev \
        libldap2-dev \
        libicu-dev \
    ; \
    rm -rf /var/lib/apt/lists/*

# Extensions PHP exigées par iTop 3.2. `mysqli` et non PDO : c'est le driver que
# le noyau d'iTop utilise. `soap` et `ldap` sont facultatives pour iTop seul mais
# requises dès qu'on active l'authentification annuaire ou les connecteurs — les
# compiler maintenant évite de reconstruire l'image le jour où l'agence les veut.
RUN set -eux; \
    docker-php-ext-configure gd --with-freetype --with-jpeg; \
    docker-php-ext-configure ldap --with-libdir="lib/$(dpkg-architecture -qDEB_HOST_MULTIARCH)/"; \
    docker-php-ext-install -j"$(nproc)" \
        mysqli \
        gd \
        zip \
        soap \
        ldap \
        intl \
        opcache \
    ; \
    docker-php-ext-enable opcache

# iTop dépasse les valeurs par défaut de PHP dès l'installation : la compilation
# du modèle de données charge plusieurs centaines de classes en mémoire, et
# l'import du schéma dure plus que les 30 s réglementaires. La valeur de
# date.timezone est réécrite au démarrage par l'entrypoint, à partir de TZ.
RUN set -eux; \
    { \
        echo 'memory_limit = 512M'; \
        echo 'max_execution_time = 300'; \
        echo 'upload_max_filesize = 64M'; \
        echo 'post_max_size = 64M'; \
        echo 'date.timezone = UTC'; \
    } > /usr/local/etc/php/conf.d/99-itop.ini

# mod_rewrite : les URL du portail iTop en dépendent.
RUN a2enmod rewrite headers

# L'archive publiée par Combodo se déplie en `web/` : c'est cette racine qui
# devient le DocumentRoot. Le téléchargement se fait à la CONSTRUCTION pour
# qu'aucun démarrage de conteneur n'ait besoin d'Internet.
WORKDIR /usr/src
RUN set -eux; \
    curl -fsSL -o itop.zip \
        "https://github.com/Combodo/iTop/releases/download/${ITOP_VERSION}/iTop-${ITOP_VERSION}-${ITOP_BUILD}.zip"; \
    unzip -q itop.zip -d /usr/src/itop-src; \
    rm itop.zip; \
    test -f /usr/src/itop-src/web/setup/unattended-install/unattended-install.php; \
    test -f /usr/src/itop-src/web/datamodels/2.x/installation.xml

# L'application reste dans /usr/src et n'est PAS copiée dans /var/www/html à la
# construction : ce dernier est un volume, et l'entrypoint ne l'y déploie que
# s'il est vide. Sans cela, reconstruire l'image écraserait la configuration et
# les extensions installées par l'exploitant.
ENV ITOP_SRC=/usr/src/itop-src/web \
    ITOP_HOME=/var/www/html \
    ITOP_REST_USER_SCRIPT=/usr/local/share/itop/create-rest-user.php

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY healthcheck.sh /usr/local/bin/healthcheck.sh
COPY create-rest-user.php /usr/local/share/itop/create-rest-user.php
RUN chmod +x /usr/local/bin/docker-entrypoint.sh /usr/local/bin/healthcheck.sh

EXPOSE 80

# Sain = l'API REST répond à l'appel exact que fait le collecteur du NOC
# (POST /webservices/rest.php, opération core/check_credentials). Une page
# d'accueil qui répond 200 ne prouverait rien : l'assistant d'installation
# aussi répond 200.
HEALTHCHECK --interval=30s --timeout=15s --start-period=600s --retries=10 \
    CMD /usr/local/bin/healthcheck.sh

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["apache2-foreground"]
