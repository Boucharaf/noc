# NetXMS web console (nxmc) — the browser UI for the netxms server. It is not
# part of the server package: NetXMS ships it as a WAR to deploy in a servlet
# container, so we unpack it into Tomcat as ROOT and let it talk to netxmsd
# over NXCP (port 4701).
#
# web.xml declares Jakarta EE 6.0, so this needs Tomcat 10.1+, not Tomcat 9.
FROM tomcat:10.1-jre17

ARG NXMC_VERSION=6.2.2
ARG NXMC_BRANCH=6.2

# The WAR is unpacked at build time rather than left for Tomcat to deploy, so
# the entrypoint can drop nxmc.properties into WEB-INF/classes before startup.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl unzip; \
    rm -rf /var/lib/apt/lists/*; \
    base="https://www.netxms.org/download/releases/${NXMC_BRANCH}"; \
    curl -fsSL "${base}/nxmc-${NXMC_VERSION}.war" -o /tmp/nxmc.war; \
    curl -fsSL "${base}/nxmc-${NXMC_VERSION}.war.sha256" -o /tmp/nxmc.war.sha256; \
    # published as "SHA2-256(stdin)= <hash>", not the coreutils format
    echo "$(sed -n 's/.*= *//p' /tmp/nxmc.war.sha256)  /tmp/nxmc.war" | sha256sum -c -; \
    rm -rf /usr/local/tomcat/webapps/ROOT; \
    mkdir -p /usr/local/tomcat/webapps/ROOT; \
    unzip -q /tmp/nxmc.war -d /usr/local/tomcat/webapps/ROOT; \
    rm -f /tmp/nxmc.war /tmp/nxmc.war.sha256

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# The console keeps one server session per browser session; the stock 128 MB
# default runs out quickly with a couple of open tabs.
ENV CATALINA_OPTS="-Xmx768m"

# netxmsd host (optionally host:port) the console connects to over NXCP.
ENV NETXMS_SERVER=netxms

EXPOSE 8080

# nxmc's own health servlet, mapped at /health by its web.xml.
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=5 \
    CMD curl -fs http://127.0.0.1:8080/health > /dev/null

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["catalina.sh", "run"]
