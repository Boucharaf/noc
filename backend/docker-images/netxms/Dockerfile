# NetXMS core server + its built-in Web API (REST v1) — the endpoint polled by
# etl/extract/netxms.py (POST /v1/login → bearer token, then /v1/alarms and
# /v1/objects). NetXMS publishes no official Docker image, so we install the
# vendor Debian packages from packages.netxms.org.
#
# The Web API is served by netxmsd itself (webapi.nxm module, section *WEBAPI in
# netxmsd.conf) — there is no separate API daemon to run.
FROM debian:bookworm-slim

# Full Debian version string so builds are reproducible; bump both together.
# Available versions: https://packages.netxms.org/debian/dists/bookworm/main/binary-amd64/Packages
ARG NETXMS_VERSION=6.2.2-1+bookworm
ARG NETXMS_SUITE=bookworm

ENV DEBIAN_FRONTEND=noninteractive

# curl stays in the image: the entrypoint bootstrap and the healthcheck talk to
# the Web API with it.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl gnupg; \
    install -d /etc/apt/keyrings; \
    curl -fsSL https://packages.netxms.org/netxms-keyring.gpg \
        -o /etc/apt/keyrings/netxms.gpg; \
    echo "deb [signed-by=/etc/apt/keyrings/netxms.gpg] https://packages.netxms.org/debian ${NETXMS_SUITE} main" \
        > /etc/apt/sources.list.d/netxms.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        netxms-base="${NETXMS_VERSION}" \
        netxms-server="${NETXMS_VERSION}" \
        netxms-agent="${NETXMS_VERSION}" \
        netxms-dbdrv-pgsql="${NETXMS_VERSION}" \
        netxms-dbdrv-sqlite3="${NETXMS_VERSION}"; \
    apt-get purge -y gnupg; \
    apt-get autoremove -y; \
    rm -rf /var/lib/apt/lists/*

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY healthcheck.sh /usr/local/bin/healthcheck.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh /usr/local/bin/healthcheck.sh

# netxmsd state: compiled MIB file, agent packages, SQLite database when used.
VOLUME ["/var/lib/netxms"]

# 8000 Web API (REST v1) · 4701 client/console · 162/udp SNMP traps ·
# 514/udp syslog
EXPOSE 8000 4701 162/udp 514/udp

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=5 \
    CMD /usr/local/bin/healthcheck.sh

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["netxmsd"]
