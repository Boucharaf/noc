# NetXMS server image

NetXMS ships no official Docker image, so this one installs the vendor Debian
packages (`packages.netxms.org`) on `debian:bookworm-slim` and runs `netxmsd`
with its **built-in Web API (REST v1)** enabled — the endpoint
`etl/extract/netxms.py` polls:

```
POST /v1/login  {"username", "password"}  ->  {"token": …}
GET  /v1/alarms          Authorization: Bearer <token>
GET  /v1/objects         Authorization: Bearer <token>
```

The Web API is a server module (`webapi.nxm`, section `*WEBAPI` in
`netxmsd.conf`), not a separate daemon: one container serves both the NetXMS
server and the REST API on port 8000.

## Build

```bash
docker build -t noc-netxms backend/docker-images/netxms
# pin another release (see the repo's Packages index):
docker build --build-arg NETXMS_VERSION=6.2.2-1+bookworm -t noc-netxms backend/docker-images/netxms
```

## What the entrypoint does

1. Writes `/etc/netxmsd.conf` from the environment (database + `*WEBAPI`
   section). Mount your own file and set `NETXMS_KEEP_CONFIG=true` to keep it.
2. Waits for the database, then initializes the schema on first start
   (`nxdbmgr init`) or runs pending upgrades on later starts.
3. Clears the `admin` account's "must change password" flag. NetXMS seeds it
   even when the password is set at init, and it makes the account answer `403`
   after a single login — which would break the collector, since it logs in on
   every poll.
4. Clears a stale database lock. `netxmsd` takes a lock row and releases it on
   shutdown; a container that is killed rather than stopped (host reboot, OOM)
   never gets there, and the next start refuses with *"Database is already
   locked by another NetXMS server instance"* until someone runs `nxdbmgr
   unlock` by hand. Only one server uses this database, so a lock found at
   startup is stale — do not point a second `netxmsd` at the same database,
   because this would let both run.
5. Starts the bundled NetXMS agent on loopback, so the server's own management
   node is actually monitored (the role `zabbix-agent` plays for Zabbix).
6. Runs `netxmsd` in the foreground as PID 1.

The `HEALTHCHECK` performs the collector's own `POST /v1/login` and requires a
token back, so "healthy" means the ETL contract works.

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `NETXMS_DB_DRIVER` | `pgsql` | `pgsql` or `sqlite` (SQLite is for throwaway installs) |
| `NETXMS_DB_HOST` / `NETXMS_DB_PORT` | `netxms-db` / `5432` | database server |
| `NETXMS_DB_NAME` / `NETXMS_DB_LOGIN` / `NETXMS_DB_PASSWORD` | `netxms` | database credentials |
| `NETXMS_DB_FILE` | `/var/lib/netxms/netxms.db` | SQLite file (SQLite only) |
| `NETXMS_ADMIN_PASSWORD` | `netxms` | password set for `admin` at init — also what the ETL uses |
| `NETXMS_WEBAPI_PORT` | `8000` | Web API listener port |
| `NETXMS_DEBUG_LEVEL` | `1` | `netxmsd` verbosity, 0–9 |
| `NETXMS_START_AGENT` | `true` | run the local agent alongside the server |
| `NETXMS_KEEP_CONFIG` | `false` | keep a mounted `/etc/netxmsd.conf` instead of generating one |

`NETXMS_ADMIN_PASSWORD` only takes effect on the **first** start (schema
init). Changing it later means changing it in the console, or wiping the
database volume.

Ports: `8000` Web API · `4701` console/client (nxmc) · `4703` agent tunnels ·
`162/udp` SNMP traps · `514/udp` syslog.

Port 4701 speaks NXCP, the NetXMS binary client protocol — it is **not** HTTP,
so a browser pointed at it gets `ERR_EMPTY_RESPONSE`. The browser console is a
separate component: see `../netxms-webui` (served on http://localhost:8086 in
this stack).

## Compose wiring

```yaml
  netxms-db:
    image: postgres:15-alpine
    environment:
      - POSTGRES_USER=${NETXMS_DB_USER:-netxms}
      - POSTGRES_PASSWORD=${NETXMS_DB_PASSWORD:-netxms_db_pass}
      - POSTGRES_DB=${NETXMS_DB_NAME:-netxms}
    volumes:
      - netxms_pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${NETXMS_DB_USER:-netxms} -d ${NETXMS_DB_NAME:-netxms}"]
      interval: 10s
      timeout: 5s
      retries: 5

  netxms:
    build: ./backend/docker-images/netxms
    hostname: netxms          # names the server's management node
    environment:
      - NETXMS_DB_HOST=netxms-db
      - NETXMS_DB_NAME=${NETXMS_DB_NAME:-netxms}
      - NETXMS_DB_LOGIN=${NETXMS_DB_USER:-netxms}
      - NETXMS_DB_PASSWORD=${NETXMS_DB_PASSWORD:-netxms_db_pass}
      - NETXMS_ADMIN_PASSWORD=${NETXMS_PASSWORD:-netxms}
    ports:
      - "8084:8000"   # Web API on the host
      - "4701:4701"   # NetXMS console
    volumes:
      - netxms_data:/var/lib/netxms
    depends_on:
      netxms-db:
        condition: service_healthy
```

Then point the collector at it in `.env` (in-network URL, no trailing `/v1`):

```
NETXMS_API_URL=http://netxms:8000
NETXMS_USER=admin
NETXMS_PASSWORD=<NETXMS_ADMIN_PASSWORD>
```

## Notes for node matching

- `GET /v1/objects` returns only the **root** objects — nodes live under
  `GET /v1/objects/2/children` (id 2 = "Infrastructure Services"). The
  collector's object-name lookup therefore usually falls back to the alarm's
  numeric `source` id, and such alarms are logged and skipped unless a
  `dim_node` matches. Name nodes after a `dim_node` code (e.g. `DED-001`) and
  match on that.
- Nodes are created in the NetXMS console (nxmc on port 4701) or over the API:
  `POST /v1/objects {"class":"Node","name":"DED-001","parentId":2,"primaryName":"10.0.0.1"}`
  — note the field names `class` and `primaryName`; unknown fields are ignored
  silently and produce an address-less node.
- To see alarms flow end to end, stop the local agent
  (`docker compose exec netxms pkill nxagentd`) and wait for the poller to
  raise the agent-unreachable alarm.
