# Architecture

Technical deep-dive into how the NOC ANPTIC Dashboard is put together. For a
quick overview and getting-started steps, see the [README](../README.md).

## Table of Contents

- [System diagram](#system-diagram)
- [Components](#components)
- [Request flow](#request-flow)
- [Incident ingestion & KPI refresh flow](#incident-ingestion--kpi-refresh-flow)
- [Real-time alerts (WebSocket)](#real-time-alerts-websocket)
- [Notifications (SMS/email/push)](#notifications-smsemailpush)
- [Scheduled jobs](#scheduled-jobs)
- [Security: RBAC & rate limiting](#security-rbac--rate-limiting)
- [Caching strategy](#caching-strategy)
- [Design system & theming](#design-system--theming)

---

## System diagram

```
                    ┌──────────────────────────────────────────┐
                    │                   NGINX                   │
                    │  :80  → 301 redirect to HTTPS              │
                    │  :443 → TLS termination (self-signed)      │
                    └──────────────────┬─────────────────────────┘
                                       │
                 ┌─────────────────────┼─────────────────────┐
                 │  /                  │  /api/*             │
         ┌───────▼────────┐   ┌────────▼────────┐
         │    Frontend     │   │     Backend      │
         │  React + Vite   │   │  FastAPI (:8000) │
         │  static (:80)   │   │                  │
         └─────────────────┘   └───┬─────────┬────┘
                                   │         │
                        ┌──────────▼──┐   ┌──▼─────────┐
                        │ PostgreSQL  │   │   Redis    │
                        │   (:5432)   │   │  (:6379)   │
                        └─────────────┘   └─────┬──────┘
                                                 │ (DB 1: broker)
                                       ┌─────────▼─────────┐
                                       │   etl-beat         │
                                       │ (Celery scheduler) │
                                       └─────────┬──────────┘
                                                 │ enqueues
                                       ┌─────────▼──────────┐
                                       │   etl-worker        │
                                       │ (Celery worker)      │
                                       │ POSTs each pass to   │
                                       │ /api/incidents/      │
                                       │        ingest/bulk   │
                                       └───────────────────────┘
```

## Components

| Container | Image / build | Role |
|---|---|---|
| `nginx` | `nginx/Dockerfile` | TLS termination, HTTP→HTTPS redirect, reverse proxy to frontend and backend |
| `frontend` | `frontend/Dockerfile` | Static React (Vite) build served by nginx-in-container on port 80 |
| `backend` | `backend/Dockerfile` | FastAPI app (Uvicorn), REST API, JWT auth + RBAC, rate limiting, KPI computation, PDF/DOCX reports, `/ws/alerts` WebSocket, SMS/email + Web Push notifications |
| `postgres` | `postgres:15-alpine` | System of record — dimensions, incidents, users; runs `database/*.sql` on first boot |
| `redis` | `redis:7` | Several roles on one instance: KPI response cache + rate-limit counters + `noc:alerts` pub/sub + collector status + the NetXMS object-identity cache (DB 0), and Celery broker (DB 1) |
| `etl-worker` | `etl/Dockerfile` | Celery worker executing `etl.collect_incident`, `etl.refresh_kpi_view`, and `etl.generate_monthly_report`; mounts the `reports` volume at `/reports` |
| `etl-beat` | `etl/Dockerfile` (different command) | Celery beat scheduler — `collect_supervision` every `ETL_COLLECT_INTERVAL_S` seconds (default 300s), `refresh_kpi_view` daily at 02:00, `generate_monthly_report` on the 1st at 02:30 |

Note: the `etl` service is Celery-based (`etl/celery_app.py`, `etl/pipelines/tasks.py`),
split into a `beat` scheduler and a `worker` process — there is no single long-running
`etl/app.py` loop.

## Request flow

1. Browser hits `https://localhost:8443` (or `:8888` for HTTP, which redirects).
2. NGINX terminates TLS and proxies:
   - `/api/*` → `backend:8000`
   - `/ws/*` → `backend:8000` (with `Upgrade`/`Connection` headers for the WebSocket handshake)
   - everything else → `frontend:80`
3. The frontend is a static SPA; all data comes from `/api/*` calls made client-side
   (Axios, see `frontend/src/api/`), authenticated with a JWT attached by an
   interceptor.
4. FastAPI routes (`backend/app/routes/`) delegate to `services/` for business logic,
   which query PostgreSQL directly via SQLAlchemy Core (`text()` queries against
   `mv_kpi_node_monthly` and `fact_incident`) — see
   [database-schema.md](database-schema.md).
5. Read-heavy KPI endpoints check Redis first (`cache_service.get_cached`) before
   hitting Postgres, and populate the cache on a miss (see
   [Caching strategy](#caching-strategy)).

## Incident ingestion & KPI refresh flow

This is the path that keeps the dashboard feeling "live":

1. `etl-beat` enqueues `etl.collect_supervision` every `ETL_COLLECT_INTERVAL_S`
   seconds (default 300, the contracted reporting granularity).
2. `etl-worker` picks up the task:
   - Loads all `is_active = TRUE` nodes (code, name, IP, source_tool) from
     Postgres (`pipelines/collector.py`).
   - Polls every **configured** supervision tool (`extract/` — a tool is
     enabled iff its `*_API_URL` env var is set): Zabbix JSON-RPC `problem.get`,
     Nagios `statusjson.cgi?query=hostlist`, NetXMS REST `/alarms`, Centreon
     REST v2 `/monitoring/resources`. Failures are isolated per tool.
   - Maps each alert onto a `dim_node` code (exact code → name → IP match,
     `extract/common.py`); unmatched hosts are logged and skipped. Sources that
     are not equipment at all (a NetXMS `BusinessService`, say) are dropped
     silently — see `HOST_CLASSES` in `extract/netxms.py`.
   - Classifies a cause from the alert text (`transform/causes.py`); text
     matching no rule stays uncategorised rather than becoming an "Autre"
     bucket.
   - Keeps no poll cursor: each collector reports what its tool has open right
     now, so a missed or failed pass is made good by the next one.
   - Normalizes events into the ingest payload shape (`transform/normalize.py`)
     and POSTs the **whole pass in one request** to
     `backend:8000/api/incidents/ingest/bulk` with
     `Authorization: Bearer $NOC_API_KEY` (`load/api_client.py`).
3. The backend's `incident_service.ingest_incidents_bulk` treats the batch as a
   **snapshot of what is currently wrong**, not a list of things to append:

   | In the batch | Already open | Result |
   |---|---|---|
   | ✅ | ❌ | created |
   | ✅ | ✅ | ignored — the same alert re-reported |
   | ❌ | ✅ | **resolved** — the alert cleared |

   - Both dedupe and reconciliation key on `(source_tool, external_id)`.
     Reconciliation is what finally closes incidents: supervision tools report
     state, so a cleared alert simply stops being listed and nothing else ever
     announces that it ended.
   - **An empty batch reconciles nothing** — it is indistinguishable from a
     collector that authenticated and returned nothing, and closing everything
     would destroy the real detection times (the next poll re-creates them as
     new incidents detected *now*).
   - One lookup per *set* of node codes and external ids, one commit, one
     `mv_kpi_node_monthly` refresh (when `SYNC_MV_REFRESH=true`) and one
     `kpi:*` cache invalidation for the whole batch. The per-incident path does
     all of that per row, which is what makes it unusable at ~1450 alarms.
4. The batch path **does not** broadcast or notify — notifying per item would
   page the permanence a thousand times for a backlog it already knows about.
   The single-incident `POST /api/incidents/ingest` still publishes to the
   `noc:alerts` Redis channel (see
   [Real-time alerts](#real-time-alerts-websocket)) and, for `critical`
   severity, schedules **two independent** FastAPI background tasks: SMS/email
   and Web Push (see [Notifications](#notifications-smsemailpush)). Anything
   that must reach a human on arrival belongs on that path.
5. Acknowledge/resolve actions (JWT + role-gated, dashboard-driven) follow the same
   commit → (refresh view for resolve) → cache-invalidate pattern.

## Real-time alerts (WebSocket)

Newly ingested incidents are pushed to open dashboards instead of waiting for
the next poll:

```
POST /api/incidents/ingest ──▶ redis PUBLISH noc:alerts ──▶ WS /ws/alerts ──▶ browser
     (any uvicorn worker)         (alert_broadcaster.py)      (routes/ws.py)     (useRealtime.js)
```

- Redis pub/sub decouples the HTTP worker that ingested the incident from the
  worker(s) holding WebSocket connections — it works unchanged with multiple
  Uvicorn workers or backend replicas.
- Each connection authenticates with a JWT **query parameter**
  (`/ws/alerts?token=…`; browsers can't set headers on a WS handshake) and is
  closed with code `4401` if invalid.
- The server sends a `{"type":"ping"}` heartbeat after ~20s of silence so
  NGINX (60s read timeout on `/ws/`) never drops an idle connection, and dead
  clients are detected by the failed send.
- On the frontend, `useRealtime.js` invalidates the react-query `alerts` and
  `kpi` caches on every incident frame; 15s polling stays on as a fallback
  when the socket can't connect (blocked upgrade, old proxy…).

## Notifications (SMS/email/push)

Two independent services react to a **critical** incident, both as FastAPI
**background tasks** scheduled after the webhook response is sent (the
supervision tool never waits on either):

**SMS/email** — `backend/app/services/notification_service.py` handles
escalation on critical incidents: the NOC lead gets an SMS (Twilio REST API, plain `requests`
call — no SDK) and the permanence list gets an email (stdlib `smtplib`,
STARTTLS). Disabled by default (`NOTIFICATIONS_ENABLED=false`); config is
`TWILIO_*`, `NOC_SMS_RECIPIENTS`, `SMTP_*`, `NOC_EMAIL_RECIPIENTS`.

**Web Push** — `backend/app/services/push_service.py` sends a VAPID-signed
push notification to every browser/PWA subscribed via
`POST /api/notifications/subscribe` (see
[integrations.md](integrations.md#web-push-browserpwa) for the full flow and
[database-schema.md](database-schema.md) for the `push_subscription` table).
No-ops if `VAPID_PUBLIC_KEY`/`VAPID_PRIVATE_KEY` aren't set; a `404`/`410`
delivery response prunes the stale subscription automatically.

Both are **fail-safe**: each no-ops per-channel when unconfigured and catches
every exception — an alerting-provider outage must never break the incident
pipeline. Neither's failure affects the other, or the webhook caller.

## Scheduled jobs

Celery beat (`etl/celery_app.py`) drives three schedules, executed by
`etl-worker`:

| Task | Schedule | What it does |
|---|---|---|
| `etl.collect_supervision` | every `ETL_COLLECT_INTERVAL_S` (default 300s) | Polls every configured supervision-tool API and POSTs each tool's whole active set to `/ingest/bulk` (creates new alerts, resolves cleared ones) |
| `etl.refresh_kpi_view` | daily **02:00** | `REFRESH MATERIALIZED VIEW CONCURRENTLY mv_kpi_node_monthly` (`CONCURRENTLY` works because the view has a unique index on `(month, node_id)`, and keeps dashboard reads unblocked while it runs) |
| `etl.generate_monthly_report` | **1st of month, 02:30** | Downloads the previous month's report from `/api/report/monthly` (PDF + DOCX, authenticating with the static API key) and archives both to the `reports` volume (`/reports`) |

The synchronous refresh-on-write in the backend (`SYNC_MV_REFRESH`, default
`true`) exists so small demo datasets reflect each ingested incident instantly; set it
to `false` in production and let the nightly job own the refresh. A bulk ingest
refreshes once per batch rather than once per incident.

Note the tension `availability_pct` introduces: it measures ongoing outages
against `NOW()`, so with the refresh disabled the availability figures are only
as fresh as the last nightly run — see
[database-schema.md](database-schema.md#mv_kpi_node_monthly).

## Security: RBAC & rate limiting

- **RBAC** (`require_role()` in `backend/app/core/security.py`): reads accept
  any authenticated role (`admin`/`analyst`/`noc_agent`); `acknowledge` and
  `resolve` require `admin` or `noc_agent` (analyst gets `403`). The frontend
  hides the acknowledge button from analysts rather than letting it fail.
- **Rate limiting** (`backend/app/core/rate_limit.py`): per-IP fixed 60s
  windows in Redis — 100/min shared across read endpoints, 10/min shared by
  `/ingest` and `/ingest/bulk` (a bulk call costs one unit however many
  incidents it carries); `429` + `Retry-After: 60` beyond that. Fail-open on Redis outage;
  behind NGINX the client IP comes from `X-Real-IP`.

## Caching strategy

- All `GET /api/kpi/*` and `GET /api/sla` endpoints are cached in Redis under
  keys like `kpi:summary:{year}:{month}`, with `CACHE_TTL` (default 300s) as
  the expiry (`app/services/cache_service.py`).
- Cache reads/writes are **fail-open**: if Redis is unreachable, `get_cached`/
  `set_cached` log a warning and return `None`/no-op rather than breaking the
  request — the endpoint just falls through to Postgres every time.
- Any incident mutation (`ingest`, `resolve`, `acknowledge`) calls
  `cache_service.invalidate_prefix("kpi:")` (or `"kpi:alerts"` for acknowledge)
  so stale KPI numbers never linger past the next write.
- `GET /api/alerts/open` is intentionally **not** cached — it's meant to reflect
  the open-incident queue in near-real-time.

## Design system & theming

The dashboard is **dark-first**: a NOC command-center aesthetic, with a fully
supported light mode toggled from the header (persisted to `localStorage`, see
`frontend/src/store/theme.js`). Tailwind v4's class-based dark variant is
enabled in `frontend/src/index.css`:

```css
@custom-variant dark (&:where(.dark, .dark *));
```

- All surface/text/accent colors are CSS custom properties (`--color-page`,
  `--color-surface`, `--color-accent`, …) defined once per theme in
  `index.css`; components read `var(--color-*)` instead of hardcoded Tailwind
  shades, so toggling the `.dark` class on `<html>` re-themes the whole app —
  charts included.
- Chart.js and Leaflet render to canvas/SVG and can't read CSS variables, so
  the same palette is mirrored as plain JS constants in
  `frontend/src/theme/colors.js`. Categorical (chart series) and status
  (severity/availability) colors were validated for lightness band, chroma
  floor, colorblind separation, and contrast against both surface colors.
- `useChartTheme()` (`frontend/src/hooks/useChartTheme.js`) exposes the active
  theme's chrome (grid/axis/ink) and categorical ramp to every chart component.
- Status colors (`good`/`warning`/`serious`/`critical`) are fixed and reused
  everywhere severity/availability is encoded — never repurposed as a generic
  chart series color.
- The supervision map (Leaflet + OpenStreetMap) only has one light cartography
  upstream, so dark mode applies a CSS filter (`invert + hue-rotate +
  contrast`) scoped to the tile pane only (`.leaflet-dark-map
  .leaflet-tile-pane`) — markers/popups sit on a separate pane and are
  unaffected. See the README's [Supervision Map](../README.md#supervision-map)
  section for marker semantics and navigation behavior.
