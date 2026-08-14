# Centreon central server (web UI + REST API v2, engine, broker, gorgone) — the
# endpoint polled by etl/extract/centreon.py (POST /login → X-AUTH-TOKEN, then
# GET /monitoring/resources). Centreon publishes no supported Docker image, so
# this one installs the vendor Debian packages from packages.centreon.com, the
# same way backend/docker-images/netxms does for NetXMS.
#
# The database lives in a separate container (centreon-db, MariaDB): Centreon
# creates both of its schemas (centreon, centreon_storage) itself during the
# install the entrypoint drives.
FROM debian:bookworm-slim

# Centreon branch and Debian suite. 24.10 is the current stable branch for
# bookworm: https://packages.centreon.com/apt-standard-24.10-stable/
ARG CENTREON_BRANCH=24.10
ARG CENTREON_SUITE=bookworm

ENV DEBIAN_FRONTEND=noninteractive

# curl stays in the image: the entrypoint drives Centreon's install wizard over
# HTTP with it, and the healthcheck calls the REST API with it.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg lsb-release procps; \
    install -d /etc/apt/keyrings; \
    curl -fsSL https://apt-key.centreon.com \
        | gpg --dearmor -o /etc/apt/keyrings/centreon.gpg; \
    echo "deb [signed-by=/etc/apt/keyrings/centreon.gpg] https://packages.centreon.com/apt-standard-${CENTREON_BRANCH}-stable/ ${CENTREON_SUITE} main" \
        > /etc/apt/sources.list.d/centreon.list; \
    echo "deb [signed-by=/etc/apt/keyrings/centreon.gpg] https://packages.centreon.com/apt-plugins-stable/ ${CENTREON_SUITE} main" \
        > /etc/apt/sources.list.d/centreon-plugins.list; \
    apt-get update; \
    apt-get install -y centreon-central; \
    apt-get purge -y gnupg; \
    apt-get autoremove -y; \
    rm -rf /var/lib/apt/lists/*

# Apache: serve PHP through Centreon's php-fpm pool only. The mod_php that
# comes with the php8.2 metapackage would be a second, unconfigured PHP, and it
# pins the prefork MPM.
RUN set -eux; \
    a2dismod php8.2 mpm_prefork; \
    a2enmod mpm_event proxy_fcgi rewrite headers setenvif

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY healthcheck.sh /usr/local/bin/healthcheck.sh
COPY centreon-service.sh /usr/local/bin/centreon-service
RUN set -eux; \
    chmod +x /usr/local/bin/docker-entrypoint.sh /usr/local/bin/healthcheck.sh \
        /usr/local/bin/centreon-service; \
    # Centreon restarts its daemons through `sudo systemctl restart …` (see
    # /etc/sudoers.d/centreon), and sudo matches the rule on the binary's path
    # — so the shim has to take systemctl's place instead of shadowing it.
    dpkg-divert --local --rename --add /usr/bin/systemctl; \
    ln -s /usr/local/bin/centreon-service /usr/bin/systemctl

# 80 web UI + REST API v2 · 5669 gorgone ZMQ (remote pollers)
EXPOSE 80 5669

# The install wizard runs on first start and takes a few minutes on a cold
# database, hence the long start period.
HEALTHCHECK --interval=30s --timeout=10s --start-period=300s --retries=10 \
    CMD /usr/local/bin/healthcheck.sh

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["centreon"]
