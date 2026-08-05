# NetXMS web console (nxmc)

NetXMS ships its console separately from the server — as a desktop app or as a
WAR for a servlet container. This image drops `nxmc-<version>.war` into Tomcat
as `ROOT.war`, so the console answers at the container root.

The console talks to `netxmsd` over **NXCP (port 4701)**, the NetXMS binary
client protocol — not over the REST API on 8000. Port 4701 is not HTTP:
pointing a browser at it yields `ERR_EMPTY_RESPONSE`.

```bash
docker build -t noc-netxms-webui backend/docker-images/netxms-webui
docker run --rm -p 8086:8080 -e NETXMS_SERVER=netxms noc-netxms-webui
```

In this stack it runs as the `netxms-webui` service: http://localhost:8086,
login `admin` / `$NETXMS_PASSWORD`.

| Setting | Default | Purpose |
|---|---|---|
| `NETXMS_SERVER` (env) | `netxms` | netxmsd host, optionally `host:port` |
| `NXMC_LOGIN` (env) | — | pre-fills the login name on the sign-in page |
| `NXMC_LANGUAGE` (env) | — | console language, e.g. `fr` |
| `CATALINA_OPTS` (env) | `-Xmx768m` | Tomcat heap; the console holds one server session per browser session |
| `NXMC_VERSION` (build arg) | `6.2.2` | console version — keep it in step with the server image |
| `NXMC_BRANCH` (build arg) | `6.2` | release directory the WAR is downloaded from |

nxmc takes its settings from a **`nxmc.properties` file on the classpath**, not
from the environment: with no such file it silently connects to `127.0.0.1:4701`
and fails with `Connection refused`. The WAR is therefore unpacked at build time
and the entrypoint generates `WEB-INF/classes/nxmc.properties` from the
variables above before Tomcat starts.

The WAR is verified against the published `.sha256` at build time. Tomcat
**10.1+** is required: `web.xml` declares Jakarta EE 6.0, so Tomcat 9 (javax
servlet) will not run it.

`GET /health` is nxmc's own health servlet and backs the image `HEALTHCHECK`.
`/` redirects to `/nxmc-light.app`, the console entry point.

The **Reporting** perspective fails with "Communication failure": it needs the
separate NetXMS reporting server (`netxms-reporting`), which this stack does not
run. Every other perspective works.
