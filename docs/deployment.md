# Deployment & Operations

Operational reference for running the NOC ANPTIC Dashboard in Docker. For a
first-time local setup, the [README's Getting Started](../README.md#getting-started)
section is the faster path — this document covers what's needed for a longer-lived
or production-style deployment.

## Table of Contents

- [Services](#services)
- [Environment variables](#environment-variables)
- [`deployment.sh`](#deploymentsh)
- [TLS certificates](#tls-certificates)
- [Data persistence & backups](#data-persistence--backups)
- [Health checks & startup order](#health-checks--startup-order)
- [Logs](#logs)
- [Production hardening checklist](#production-hardening-checklist)

---

## Services

Defined in `docker-compose.yml`. The dashboard stack proper:

| Service | Build context | Exposed port(s) | Depends on (healthy) |
|---|---|---|---|
| `nginx` | `./nginx` | `8888:80`, `8443:443` | `backend`, `frontend` |
| `frontend` | `./frontend` | `3000:80` | `backend` |
| `backend` | `./backend` | `8000` (container-only unless mapped) | `redis`, `postgres` |
| `etl-worker` | `./etl` (`celery ... worker`) | — | `backend`, `redis` |
| `etl-beat` | `./etl` (`celery ... beat`) | — | `redis` |
| `redis` | `redis:7` | `6379` | — |
| `postgres` | `postgres:15-alpine` | `5432` | — |

Plus the **bundled supervision/ITSM servers** the collectors poll (see
[integrations.md](integrations.md)):

| Service | Image | Exposed port(s) | Notes |
|---|---|---|---|
| `zabbix-server` | `zabbix/zabbix-server-pgsql:alpine-7.0-latest` | `10051:10051` | trapper port for LAN agents |
| `zabbix-web` | `zabbix/zabbix-web-nginx-pgsql:alpine-7.0-latest` | `8081:8080` | UI + JSON-RPC API, `Admin`/`zabbix` |
| `zabbix-agent` | `zabbix/zabbix-agent2:alpine-7.0-latest` | — | monitors the Zabbix host itself |
| `zabbix-db` | `postgres:15-alpine` | — | Zabbix's own database |
| `nagios` | `jasonrivers/nagios:latest` | `8083:80` | `$NAGIOS_USER`/`$NAGIOS_PASSWORD` |
| `itop` | `vbkunin/itop:3.2.2` | `8082:80` | embedded MariaDB; one-time setup wizard |

`etl-worker` and `etl-beat` share the same image/Dockerfile but run different
Celery commands (`worker` vs `beat`) — see [architecture.md](architecture.md#components).

Named volumes: `pgdata` (Postgres data), `reports` (mounted at `/reports` in
`etl-worker` — the scheduled end-of-month job archives each month's PDF/DOCX
report there; see
[architecture.md#scheduled-jobs](architecture.md#scheduled-jobs)), plus
`zbx_pgdata` (Zabbix DB), `nagios_etc` (Nagios host/service definitions), and
`itop_mysql`/`itop_html` (iTop database and installed app/config — the setup
wizard's work survives container recreation). To pull an archived report out
of the volume:

```bash
docker compose exec etl-worker ls /reports
docker compose cp etl-worker:/reports/rapport-noc-2026-06.pdf .
```

## Environment variables

All configuration is via `.env` in the project root (see `.env.example` for the
full template). Grouped by concern:

**Database**
`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_HOST`, `POSTGRES_PORT`

**Redis / cache**
`REDIS_HOST`, `REDIS_PORT`, `CACHE_TTL` (seconds, default 300)

**Backend security**
`SECRET_KEY` (JWT signing — **must** be changed for any non-local deployment),
`ALGORITHM` (`HS256`), `ACCESS_TOKEN_EXPIRE_MINUTES`, `NOC_API_KEY` (static
bearer key for `/api/incidents/ingest` webhooks), `CORS_ORIGINS`
(comma-separated allow-list)

**Supervision tool collectors** (a collector is enabled iff its `*_API_URL`
is set — see [integrations.md](integrations.md))
`ZABBIX_API_URL` + `ZABBIX_USER`/`ZABBIX_PASSWORD` or `ZABBIX_API_TOKEN`,
`NAGIOS_API_URL` + `NAGIOS_USER`/`NAGIOS_PASSWORD` and/or `NAGIOS_API_KEY`,
`NETXMS_API_URL` + `NETXMS_USER`/`NETXMS_PASSWORD`,
`CENTREON_API_URL` + `CENTREON_USER`/`CENTREON_PASSWORD` or `CENTREON_API_KEY`,
`ITOP_URL`/`ITOP_USER`/`ITOP_PASS`/`ITOP_ORG_ID` (real REST ticket creation —
see [integrations.md](integrations.md#itop-itsm--cmdb) for the one-time setup
wizard + `REST Services User` profile grant it requires)

**Bundled supervision servers**
`ZABBIX_DB_USER`/`ZABBIX_DB_PASSWORD`/`ZABBIX_DB_NAME` (the `zabbix-db`
container), `ITOP_DB_PASSWORD` (iTop's embedded MariaDB `admin` user).
`NAGIOS_USER`/`NAGIOS_PASSWORD` double as the Nagios container's `nagiosadmin`
web credentials.

**Notifications** (SMS + email on critical incidents — see
[architecture.md#notifications-smsemailpush](architecture.md#notifications-smsemailpush))
`NOTIFICATIONS_ENABLED` (default `false`), `TWILIO_ACCOUNT_SID`,
`TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, `NOC_SMS_RECIPIENTS`
(comma-separated), `SMTP_HOST`, `SMTP_PORT` (default 587), `SMTP_USER`,
`SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_USE_TLS`, `NOC_EMAIL_RECIPIENTS`
(comma-separated)

**Web Push** (browser/PWA push on critical incidents — see
[integrations.md](integrations.md#web-push-browserpwa) for how to generate a
keypair)
`VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_CLAIMS_EMAIL` — generate a
fresh keypair per environment; never reuse the demo one shipped in this repo's
`.env` in production.

**Rate limiting**
`RATE_LIMIT_ENABLED` (default `true`), `RATE_LIMIT_READ_PER_MIN` (default 100),
`RATE_LIMIT_INGEST_PER_MIN` (default 10)

**Materialized view refresh**
`SYNC_MV_REFRESH` (default `true`: refresh `mv_kpi_node_monthly` on every
write — demo behavior; set `false` in production and rely on the nightly
02:00 `etl.refresh_kpi_view` job)

**ETL / Celery**
`CELERY_BROKER_DB` (Redis logical DB for the broker, default 1 — separate from
the backend's cache on DB 0), `ETL_COLLECT_INTERVAL_S` (seconds between
supervision-API polls, default 300 — spec §2.2), `REPORTS_DIR` (where the monthly report job
writes, default `/reports`)

**Global**
`ENVIRONMENT`, `DEBUG`, `LOG_LEVEL`

> `.env` is gitignored. Never commit real credentials — for a production
> deployment, source these from a secrets manager instead of a checked-in file.

## `deployment.sh`

A minimal one-shot redeploy script at the project root:

```bash
#!/bin/bash
set -e
echo "Deploying at $(date)..."
docker compose down
docker compose up --build -d
```

Usage:

```bash
./deployment.sh
```

This is a **full stop/rebuild/restart** — it briefly takes the whole stack
(including Postgres/Redis containers, though not their volumes) offline while
images rebuild. It does **not**:
- Pull new source (run `git pull` first if deploying a new commit).
- Preserve in-flight Celery tasks (`etl-worker`/`etl-beat` restart cleanly, but
  any task mid-flight during `down` is lost — acceptable: the next collection
  pass re-fetches from each tool's last-poll timestamp).
- Touch the `pgdata` volume — database contents persist across runs.

For a zero-downtime rolling update, rebuild and restart one service at a time
instead (`docker compose up --build -d backend`, etc.) rather than using this
script.

## TLS certificates

`nginx/generate_cert.sh` creates a **self-signed** certificate at
`nginx/certs/noc-selfsigned.crt`/`.key`, valid 825 days, with SANs for
`noc.anptic.bf`, `noc-api.anptic.bf`, `localhost`, and `127.0.0.1`. It satisfies
the cahier des charges' "HTTPS obligatoire" (§10.1) requirement for local/demo
use, but browsers and `curl` will flag it as untrusted since it isn't
CA-signed.

Regenerate it (e.g. after expiry, or to add a SAN):

```bash
./nginx/generate_cert.sh
docker compose restart nginx
```

**For a real deployment**, replace the two files in `nginx/certs/` with a
certificate from Let's Encrypt or ANPTIC's internal CA — the CN/SAN already
match the production domains referenced in the README and cert script.
`nginx/certs/` is gitignored; never commit private keys.

## Data persistence & backups

Postgres data lives in the named Docker volume `pgdata` (`noc_pgdata` once
namespaced by the `noc` compose project), mounted at
`/var/lib/postgresql/data`. Redis has no volume — it's pure cache/broker state
and is safe to lose on restart (KPI cache repopulates from Postgres; Celery
beat just re-schedules).

**Backup** (while the stack is running):

```bash
docker compose exec postgres pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > backup.sql
```

**Restore** into a fresh volume:

```bash
docker compose down
docker volume rm noc_pgdata
docker compose up -d postgres
# wait for postgres to become healthy, then:
cat backup.sql | docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"
docker compose up -d
```

Note that `database/01_schema.sql` + `database/02_seed.sql` only auto-run via
`docker-entrypoint-initdb.d` on a **fresh, empty** volume — restoring a real
backup this way means the seed data won't re-run (the schema/tables already
exist from the dump), which is what you want in a real restore scenario.

## Health checks & startup order

Every service has a Docker healthcheck, and `depends_on: condition:
service_healthy` enforces startup order:

```
postgres, redis  →  backend  →  frontend  →  nginx
                     ↑
                  etl-worker, etl-beat
```

`docker compose ps` shows health status per container; a service stuck in
`starting`/`unhealthy` is the first thing to check when the stack doesn't come
up cleanly.

## Logs

```bash
docker compose logs -f                # everything
docker compose logs -f backend        # one service
docker compose logs -f etl-worker etl-beat   # ETL pipeline only
```

`LOG_LEVEL` (default `INFO`) controls both Celery services' verbosity, and
also the backend's root logger (`logging.basicConfig` in `app/main.py`) — app
loggers like `notification_service`/`push_service`/`itop_service` only emit at
or above this level.

## Production hardening checklist

Before pointing this at real traffic / real supervision tools:

- [ ] Replace `SECRET_KEY` and `NOC_API_KEY` with strong, unique values.
- [ ] Replace the self-signed TLS cert with a CA-issued one (see above).
- [ ] Set real `ZABBIX_*` / `CENTREON_*` / `NAGIOS_*` credentials so the
      collectors poll the real supervision APIs.
- [ ] Set real `ITOP_*` credentials and complete the setup wizard + grant the
      `REST Services User` profile to the API account (ticket creation fails
      silently — logged, not surfaced — without it; see
      [integrations.md](integrations.md#itop-itsm--cmdb)).
- [ ] Generate a **fresh** `VAPID_PUBLIC_KEY`/`VAPID_PRIVATE_KEY` pair for Web
      Push — do not reuse the demo keypair shipped in this repo's `.env` (see
      [integrations.md](integrations.md#web-push-browserpwa)).
- [ ] Set `SYNC_MV_REFRESH=false` so the nightly 02:00 `etl.refresh_kpi_view`
      job owns the materialized-view refresh (per-write refresh gets expensive
      at production incident volume).
- [ ] Configure and enable notifications: real Twilio + SMTP credentials,
      `NOC_SMS_RECIPIENTS`/`NOC_EMAIL_RECIPIENTS`, then
      `NOTIFICATIONS_ENABLED=true`.
- [ ] Keep `RATE_LIMIT_ENABLED=true` and review the per-minute budgets for the
      expected number of NOC users behind shared IPs.
- [ ] Restore map attribution or move off the public OSM tile servers (see
      [README Supervision Map](../README.md#supervision-map)) before any
      public-facing deployment.
- [ ] Tighten `CORS_ORIGINS` to the real frontend domain(s) only.
- [ ] Set up recurring `pg_dump` backups (see above) rather than relying on
      volume durability alone.
- [ ] Change all seeded demo account passwords/PINs (see
      [README Authentication](../README.md#authentication)) or remove the demo
      users entirely before go-live.
