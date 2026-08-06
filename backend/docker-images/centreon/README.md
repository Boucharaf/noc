# Centreon central image

Centreon ships no supported Docker image, so this one installs the vendor
Debian packages (`packages.centreon.com`) on `debian:bookworm-slim` and runs a
complete **central server** — web UI, **REST API v2**, monitoring engine,
broker and gorgone — with the install wizard driven **unattended** on first
start.

The API is what `etl/extract/centreon.py` polls:

```
POST /centreon/api/latest/login  {"security":{"credentials":{"login","password"}}}
                                                  ->  {"security":{"token": …}}
GET  /centreon/api/latest/monitoring/resources    X-AUTH-TOKEN: <token>
```

## Build

```bash
docker build -t noc-centreon backend/docker-images/centreon
# another branch (see https://packages.centreon.com/):
docker build --build-arg CENTREON_BRANCH=24.04 -t noc-centreon backend/docker-images/centreon
```

## What the entrypoint does

1. Writes the PHP settings Centreon needs (`date.timezone`, no execution time
   limit for the multi-MB SQL imports) and starts php-fpm and Apache.
2. On first start only — recognised by the absence of
   `/etc/centreon/centreon.conf.php` — runs the install wizard end to end:
   prerequisites, engine and broker paths, admin account, database access, then
   the seven install steps (configuration files, both schemas, database user,
   base configuration, partitioning, cache) and the module installation. Any
   step that fails aborts the start with Centreon's own error message.
3. Grants the database user on `'%'`. The wizard grants it on the container's
   IP address, which compose changes whenever it recreates the container.
4. Creates a host for the central itself (ping on 127.0.0.1) when the
   configuration has no host yet, so the poller — and the collector — have
   something real to report. This is the role `zabbix-agent` plays for Zabbix.
5. Exports the poller configuration from the database to
   `/etc/centreon-engine` and `/etc/centreon-broker` (CLAPI `POLLERGENERATE` +
   `CFGMOVE`), then starts `cbd`, `centengine` and `gorgoned`.
6. Keeps Apache in the foreground as the container's main process.

The `HEALTHCHECK` performs the collector's own `POST …/login` and requires a
token back, so "healthy" means the ETL contract works.

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `CENTREON_DB_HOST` / `CENTREON_DB_PORT` | `centreon-db` / `3306` | MariaDB server (≥ 10.5) |
| `CENTREON_DB_ROOT_USER` / `CENTREON_DB_ROOT_PASSWORD` | `root` / `centreon_db_root` | used by the install to create the schemas |
| `CENTREON_DB_USER` / `CENTREON_DB_PASSWORD` | `centreon` / `centreon_db_pass` | account Centreon itself connects with |
| `CENTREON_DB_NAME` / `CENTREON_DB_STORAGE_NAME` | `centreon` / `centreon_storage` | configuration and real-time schemas |
| `CENTREON_ADMIN_PASSWORD` | `Centreon!2024` | password set for `admin` at install — also what the ETL uses |
| `CENTREON_ADMIN_EMAIL` / `_FIRSTNAME` / `_LASTNAME` | `admin@centreon.local` / `Centreon` / `Admin` | admin contact details |
| `CENTREON_MONITOR_SELF` | `true` | create the self-monitoring host on an empty configuration |
| `CENTREON_SELF_HOST_NAME` | container hostname | name of that host |
| `CENTREON_INSTALL_MODULES` | `true` | install the packaged modules during the wizard |
| `CENTREON_APPLY_CONFIG` | `true` | export the poller configuration on every start |
| `CENTREON_START_MONITORING` | `true` | run cbd/centengine/gorgoned (`false` = web only) |
| `CENTREON_PHP_MEMORY_LIMIT` | `512M` | PHP `memory_limit` |
| `TZ` | `Europe/Paris` | PHP timezone |

`CENTREON_ADMIN_PASSWORD` only takes effect on the **first** start, and the
wizard enforces Centreon's password policy: at least 12 characters with a lower
case, an upper case, a digit and one of `@$!%*?&`, and **no character outside
that set** — a `-` or `_` is refused. The entrypoint checks it up front and
stops with that message rather than failing halfway through the install.

Ports: `80` web UI + REST API (both under `/centreon`) · `5669` gorgone ZMQ for
remote pollers.

## Database prerequisites

The installer refuses to create its schemas unless the MariaDB server has
`innodb_file_per_table=1` and `open_files_limit ≥ 32000`, so the `centreon-db`
service passes both (and raises the container's `nofile` ulimit accordingly).

## Compose wiring

```yaml
  centreon-db:
    image: mariadb:10.11
    command: ["--innodb-file-per-table=1", "--open-files-limit=32000"]
    environment:
      - MARIADB_ROOT_PASSWORD=${CENTREON_DB_ROOT_PASSWORD}
    ulimits:
      nofile: { soft: 40000, hard: 40000 }
    volumes:
      - centreon_dbdata:/var/lib/mysql
    healthcheck:
      test: ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"]

  centreon:
    build: ./backend/docker-images/centreon
    hostname: centreon          # names the host the central creates for itself
    environment:
      - CENTREON_DB_HOST=centreon-db
      - CENTREON_DB_ROOT_PASSWORD=${CENTREON_DB_ROOT_PASSWORD}
      - CENTREON_DB_USER=${CENTREON_DB_USER}
      - CENTREON_DB_PASSWORD=${CENTREON_DB_PASSWORD}
      - CENTREON_ADMIN_PASSWORD=${CENTREON_PASSWORD}
    ports:
      - "8084:80"
    volumes:
      - centreon_etc:/etc/centreon
      - centreon_gorgone_etc:/etc/centreon-gorgone
      - centreon_engine_etc:/etc/centreon-engine
      - centreon_broker_etc:/etc/centreon-broker
      - centreon_varlib:/var/lib/centreon
      - centreon_broker_varlib:/var/lib/centreon-broker
    depends_on:
      centreon-db:
        condition: service_healthy
```

Then point the collector at it in `.env` (in-network URL, API base **with**
`/centreon/api/latest`):

```
CENTREON_API_URL=http://centreon/centreon/api/latest
CENTREON_USER=admin
CENTREON_PASSWORD=<CENTREON_ADMIN_PASSWORD>
```

The volumes hold everything the install writes outside the database. Without
them a recreated container would find its schemas already populated and refuse
to install again — if you ever need a clean slate, drop `centreon_dbdata`
together with all of them.

## Running the daemons without systemd

`cbd`, `centengine`, `gorgoned` and `centreontrapd` are started by
`centreon-service`, a small PID-file supervisor. It is also installed **as**
`/usr/bin/systemctl` (the real binary is diverted to `systemctl.distrib`),
because Centreon's own sudoers rules whitelist
`sudo /usr/bin/systemctl restart centengine` — that is the path the web UI's
"Export configuration → Restart" takes to reach the poller, and it works here
as a result.

```bash
docker compose exec centreon centreon-service status cbd centengine gorgoned
docker compose exec centreon centreon-service restart centengine
```

Their stdout goes to `/var/log/centreon-docker/*.out`, tailed into
`docker compose logs centreon`; the daemons' own logs stay in
`/var/log/centreon-engine`, `/var/log/centreon-broker` and
`/var/log/centreon-gorgone`.

## Notes for node matching

- The collector reports resources whose status is `CRITICAL`, `UNKNOWN` or
  `DOWN` and are still unhandled, matching them to a `dim_node` by host name
  (for a service, its **parent host**), so name hosts after a node code
  (e.g. `DED-001`); unmatched hosts are logged and skipped.
- A fresh Centreon has no host templates: they come from plugin packs, which
  are imported from Centreon's repository and need a licence. Hosts created by
  hand with an explicit check command — the way the entrypoint creates the
  central's own — work without them.
- To see an incident flow end to end, add a host pointing at an unreachable
  address and let it go DOWN:

  ```bash
  docker compose exec centreon bash -c '
    C="/usr/share/centreon/bin/centreon -u admin -p $CENTREON_ADMIN_PASSWORD"
    $C -o HOST -a add -v "DED-001;Demo;192.0.2.1;;Central;"
    for p in check_command\;check_local_ping max_check_attempts\;1 \
             check_interval\;1 retry_check_interval\;1 check_period\;24x7 \
             active_checks_enabled\;1 notifications_enabled\;0; do
      $C -o HOST -a setparam -v "DED-001;$p"
    done
    $C -a POLLERGENERATE -v 1 && $C -a CFGMOVE -v 1 && systemctl restart centengine'
  ```
