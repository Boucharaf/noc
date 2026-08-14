# 🖥️ NOC ANPTIC Dashboard

> **Tableau de bord du Centre des Opérations Réseau (NOC) de l'ANPTIC**  
> Network Operations Center dashboard for centralized KPI monitoring, availability tracking, and real-time incident management.

---

## 📋 Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Design System & Theming](#design-system--theming)
- [Prerequisites](#prerequisites)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
  - [1. Clone the Repository](#1-clone-the-repository)
  - [2. Configure Environment Variables](#2-configure-environment-variables)
  - [3. Run with Docker (Recommended)](#3-run-with-docker-recommended)
  - [4. Run Locally (Development)](#4-run-locally-development)
- [Services & Ports](#services--ports)
  - [First-run setup of the bundled tools](#first-run-setup-of-the-bundled-tools)
- [Supervision Map](#supervision-map)
  - [The Carte tab](#the-carte-tab)
- [Authentication](#authentication)
- [Branding: Logo & Favicon](#branding-logo--favicon)
- [Integrations](#integrations)
- [Progressive Web App & Push Notifications](#progressive-web-app--push-notifications)
- [API Documentation](#api-documentation)
- [Demo Data & ETL Collection](#demo-data--etl-collection)
- [Restoring the production NetXMS dump](#restoring-the-production-netxms-dump)
  - [What the restore requires](#what-the-restore-requires)
  - [What you get, and what you don't](#what-you-get-and-what-you-dont)
  - [Restoring by hand](#restoring-by-hand)
  - [Verify](#verify)
  - [Checklist](#checklist)
- [Loading the real CMDB](#loading-the-real-cmdb)
- [Incident lifecycle](#incident-lifecycle)
  - [Availability](#availability)
- [KPI calculations](#kpi-calculations)
  - [1. Base measures](#1-base-measures--computed-by-postgresql-on-fact_incident)
  - [2. Per node-month](#2-per-node-month--mv_kpi_node_monthly)
  - [3. Network-wide KPI cards](#3-network-wide--the-kpi-cards-get-apikpisummary)
  - [4. SLA indicators](#4-sla-indicators-get-apisla)
  - [5. Recurrent and flapping nodes](#5-recurrent-and-flapping-nodes-get-apikpirecurrent)
  - [6. The remaining views](#6-the-remaining-views)
- [Collector status](#collector-status)
- [Further Documentation](#further-documentation)
- [Contributing](#contributing)

---

## Overview

The NOC ANPTIC Dashboard centralizes network availability KPIs and incident data in real time. It integrates with industry-standard monitoring tools:

- **[Zabbix](https://www.zabbix.com/)** — Infrastructure and network monitoring
- **[Nagios](https://www.nagios.org/)** — IT infrastructure monitoring
- **[Centreon](https://www.centreon.com/)** — IT monitoring and observability platform
- **[NetXMS](https://www.netxms.org/)** — Network and infrastructure monitoring
- **[iTop](https://www.combodo.com/itop)** — IT Service Management (ITSM) & CMDB

---

## Architecture

The application follows a **containerized 3-tier architecture** orchestrated via Docker Compose:

```
                        ┌─────────────────────────────────────────────┐
                        │                   NGINX                      │
                        │   :80 → 301 redirect     :443 TLS (self-      │
                        │                          signed cert)         │
                        └──────────────────┬──────────────────────────┘
                                           │
                        ┌──────────────────┴──────────────────┐
                        │                                      │
              ┌─────────▼──────────┐              ┌───────────▼────────┐
              │     Frontend       │              │      Backend       │
              │  React + Vite      │              │  FastAPI (Python)  │
              │     (:3000)        │              │      (:8000)       │
              └────────────────────┘              └──────┬─────┬───────┘
                                                         │     │
                                              ┌──────────▼─┐ ┌▼──────────┐
                                              │ PostgreSQL  │ │   Redis   │
                                              │  Database  │ │   Cache   │
                                              │  (:5432)   │ │  (:6379)  │
                                              └────────────┘ └───────────┘

                        ┌─────────────────────────────────────────────┐
                        │  ETL collectors — poll the configured         │
                        │  Zabbix/Nagios/NetXMS/Centreon/iTop APIs      │
                        │  every 5 min and POST one batch per tool to   │
                        │  /api/incidents/ingest/bulk                   │
                        └─────────────────────────────────────────────┘
```

| Layer | Technology | Role |
|---|---|---|
| **Frontend** | React 19 + Vite | Interactive real-time dashboard UI (WebSocket push + polling fallback) |
| **Backend** | FastAPI (Python 3.12) | REST API, KPI computation, webhooks, JWT auth + RBAC, rate limiting, WebSocket alert stream, PDF/DOCX reports |
| **Database** | PostgreSQL 15 | Persistent storage (dimensions, incidents, users) |
| **Cache** | Redis 7 | KPI caching, rate-limit counters, Celery broker, alert pub/sub |
| **Proxy** | NGINX | TLS termination, HTTP→HTTPS redirect, reverse proxy (`/api`, `/ws`) |
| **ETL** | Python + Celery | Polls the configured Zabbix/Nagios/NetXMS/Centreon/iTop APIs (5-min batch); nightly KPI refresh (02:00); end-of-month report archive |
| **Notifications** | Twilio + SMTP + Web Push | SMS + email (off by default) and browser push (PWA) to the NOC on critical incidents |

---

## Tech Stack

### Backend
- **[FastAPI](https://fastapi.tiangolo.com/)** `0.103.1` — Modern async Python web framework
- **[SQLAlchemy](https://www.sqlalchemy.org/)** `2.0.36` — Python ORM
- **[Uvicorn](https://www.uvicorn.org/)** `0.23.2` — ASGI server
- **[Psycopg2](https://www.psycopg.org/)** `2.9.10` — PostgreSQL adapter
- **[Redis-py](https://redis-py.readthedocs.io/)** `5.0.0` — Redis client (cache, rate limiting, pub/sub)
- **[fpdf2](https://pypi.org/project/fpdf2/)** `2.7.9` — Monthly report PDF export
- **[python-docx](https://pypi.org/project/python-docx/)** `1.1.2` — Monthly report DOCX export
- **[websockets](https://pypi.org/project/websockets/)** `12.0` — WebSocket support for the `/ws/alerts` stream
- **[Requests](https://pypi.org/project/requests/)** `2.32.3` — Outbound HTTP (Twilio SMS API)
- **[pywebpush](https://pypi.org/project/pywebpush/)** `2.0.3` — VAPID-signed Web Push delivery to browser/PWA subscriptions
- **[Python-dotenv](https://pypi.org/project/python-dotenv/)** `1.0.0` — Environment variable management
- **[pytest](https://pytest.org/) + [httpx](https://www.python-httpx.org/)** *(dev)* — Backend test suite (`backend/tests/`)

### Frontend
- **[React](https://react.dev/)** `19` — UI library
- **[Vite](https://vite.dev/)** `8` — Build tool & dev server
- **[TailwindCSS](https://tailwindcss.com/)** `4` — Utility-first CSS framework
- **[TanStack Query](https://tanstack.com/query)** `5` — Server state management & caching
- **[Axios](https://axios-http.com/)** — HTTP client
- **[Chart.js](https://www.chartjs.org/) + react-chartjs-2** — Data visualization & charting
- **[Leaflet](https://leafletjs.com/) + react-leaflet** — Supervision map (OpenStreetMap tiles)
- **[Zustand](https://zustand-demo.pmnd.rs/)** `5` — Global state management
- **[React Router DOM](https://reactrouter.com/)** `7` — Client-side routing
- **[Lucide React](https://lucide.dev/)** — Icon library
- **[date-fns](https://date-fns.org/)** — Date utility library
- **[vite-plugin-pwa](https://vite-pwa-org.netlify.app/)** `1.3.0` + **workbox-precaching** `7.4.1` — PWA build (installable, offline-capable) with a custom service worker (`src/sw.js`) handling Web Push and notification clicks
- **[oxlint](https://oxc.rs/docs/guide/usage/linter)** `1` *(dev)* — linter behind `npm run lint` (config in `frontend/.oxlintrc.json`)

---

## Design System & Theming

The dashboard is **dark-first**: a NOC command-center aesthetic, with a fully supported light mode reached via the sun/moon toggle in the header (state persisted in `localStorage`, see `frontend/src/store/theme.js`). Tailwind v4's class-based dark variant is enabled in `frontend/src/index.css`:

```css
@custom-variant dark (&:where(.dark, .dark *));
```

All surface/text/accent colors are CSS custom properties (`--color-page`, `--color-surface`, `--color-accent`, …) defined once for each theme in `index.css`, so components read `var(--color-*)` rather than hardcoding Tailwind gray/blue shades — flipping the `.dark` class on `<html>` re-themes the whole app instantly, charts included.

Chart/map colors can't use CSS variables (Chart.js and Leaflet's canvas/SVG rendering don't see them), so the same palette is mirrored as plain JS constants in `frontend/src/theme/colors.js`:

- **Categorical** (chart series) and **status** (severity/availability) colors were run through the [dataviz skill](https://github.com/anthropics/claude-code)'s six-check validator — lightness band, chroma floor, CVD (colorblind) separation, and contrast — against both the light (`#fcfcfb`) and dark (`#0b1220`) surfaces actually used here.
- `useChartTheme()` (`frontend/src/hooks/useChartTheme.js`) exposes the active theme's chrome (grid/axis/ink) and categorical ramp to every Chart.js component.
- Status colors (`good`/`warning`/`serious`/`critical`) are fixed and reused everywhere severity or availability is encoded (badges, map markers, SLA trackers) — never repurposed as a chart series color.

---

## Prerequisites

Ensure you have the following installed before running the project:

| Tool | Minimum Version | Install |
|---|---|---|
| **Docker** | 24+ | [docs.docker.com](https://docs.docker.com/get-docker/) |
| **Docker Compose** | 2.20+ | Included with Docker Desktop |
| **Git** | Any | [git-scm.com](https://git-scm.com/) |
| **Node.js** *(dev only)* | 20+ | [nodejs.org](https://nodejs.org/) |
| **Python** *(dev only)* | 3.12+ | [python.org](https://www.python.org/) |

---

## Project Structure

```
noc/
├── .env                          # Environment variables (gitignored — ⚠️ never commit secrets!)
├── .env.example                  # Documented template for .env — copy it to start
├── .gitignore
├── docker-compose.yml            # Docker service definitions (app + the 5 bundled supervision tools)
├── deployment.sh                 # One-shot redeploy: docker compose down && up --build -d
├── README.md                     # This file
├── SERVER_DATA.md                # Field-by-field mapping: each tool's API payload → the star schema
├── schema.pdf                    # Star-schema diagram (reference document; the app draws its own)
├── docs/                         # Deep-dive reference — see "Further Documentation"
│   ├── architecture.md
│   ├── api-reference.md
│   ├── database-schema.md
│   ├── deployment.md
│   └── integrations.md
│
├── database/
│   ├── 01_schema.sql             # DB schema (tables, indexes, materialized view, dim_user)
│   ├── 02_seed.sql               # Generated demo dataset (see below) — auto-run after the schema
│   ├── generate_seed.py          # Regenerates 02_seed.sql (regions/localities/nodes/incidents/demo users)
│   └── restore_netxms_dump.sh    # Restores the production NetXMS pg_dump into netxms-db (:5438, NOT the app DB)
│
├── nginx/                        # Public gateway — the only published entry point
│   ├── Dockerfile
│   ├── nginx.conf                # HTTP->HTTPS redirect + TLS termination + reverse proxy (/api/, /ws/, /)
│   ├── generate_cert.sh          # Regenerates the self-signed cert in certs/
│   └── certs/                    # Self-signed TLS cert/key (gitignored — never commit)
│
├── backend/                      # FastAPI application (Python 3.12)
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── requirements-dev.txt      # + pytest/httpx for the test suite
│   ├── pytest.ini
│   ├── tests/                    # Backend test suite (auth, RBAC, rate limiting, ingest flow, reports…)
│   ├── docker-images/            # Images built here because upstream publishes none (each has its own README)
│   │   ├── centreon/             # Centreon central (web + engine + broker + gorgone) on one image
│   │   ├── netxms/               # netxmsd + the built-in Web API (REST v1), on its own PostgreSQL
│   │   └── netxms-webui/         # Tomcat + nxmc.war — the console speaks NXCP/4701, not HTTP
│   └── app/
│       ├── main.py               # FastAPI entry point, CORS + router wiring
│       ├── core/                 # Config/constants, security (JWT + RBAC + webhook API key), rate limiting
│       ├── db/                   # SQLAlchemy session & Redis client
│       ├── models/               # SQLAlchemy ORM models (dimensions, fact_incident, KPI view, dim_user, push_subscription)
│       ├── schemas/              # Pydantic request/response schemas
│       ├── routes/               # REST routers (/api/kpi, /api/sla, /api/alerts, /api/incidents, /api/auth,
│       │                         #   /api/report, /api/notifications, /api/interop) + the /ws/alerts WebSocket
│       ├── services/             # Business logic (KPI queries, incident lifecycle, cache, auth, PDF/DOCX report,
│       │                         #   SMS/email + Web Push notifications, alert broadcast, collector status)
│       └── templates/            # incident_alert.html — the critical-incident notification email
│
├── frontend/                     # React application (Vite) — built and served by its own nginx in the image
│   ├── Dockerfile                # node build stage → nginx:alpine serving /usr/share/nginx/html
│   ├── nginx.conf                # SPA fallback (try_files … /index.html) for the container
│   ├── package.json
│   ├── vite.config.js            # PWA plugin + a dev-server proxy: /api -> localhost:8000
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   ├── .oxlintrc.json            # oxlint config (`npm run lint`)
│   ├── index.html                # Favicon links + <title>
│   ├── public/                   # favicon.ico, favicon-*.png, apple-touch-icon.png, icon-*.png
│   └── src/
│       ├── App.jsx               # Root component + route protection (redirects to /login)
│       ├── main.jsx              # React entry point (wraps app in QueryClientProvider)
│       ├── index.css             # Design tokens (CSS vars per theme) + Leaflet theming
│       ├── theme/colors.js       # Chart/map color constants (validated palette, mirrors index.css)
│       ├── assets/images/        # Brand assets (master logo + the 256px variant the UI imports)
│       ├── sw.js                 # Custom service worker (injectManifest strategy): precache + push/notificationclick handlers
│       ├── api/                  # Axios HTTP clients (kpi, sla, alerts, auth, report, notifications, interop) + auth interceptor
│       ├── components/           # Reusable UI components
│       │   ├── charts/           # Chart.js components: TrendLine, WeeklyBar, HourHeatmap, MTTRDonut (theme-aware)
│       │   ├── map/              # BurkinaFasoMap (Leaflet/OSM) + LocalityBulletList
│       │   ├── layout/           # Header (incl. push-notification bell toggle), TabNav
│       │   └── …                 # KPICard, AlertFeed, IncidentTable, NodeList, SLATracker,
│       │                         #   PeriodComparison, NotificationsBell, Card, Badge
│       ├── hooks/                # useKPI, useRealtime, useChartTheme, useClock, usePushNotifications,
│       │                         #   useSessionKeepAlive, usePeriodAutoSync
│       ├── utils/                # format.js — shared display formatters (incident age)
│       ├── pages/                # Login + dashboard views (Global, Localities, Carte, SLA, Interop, Data Model)
│       └── store/                # Zustand stores: period, theme, auth (persisted, incl. session expiry)
│
└── etl/                          # Collector + scheduled jobs service (see "Demo Data & ETL Collection" below)
    ├── celery_app.py             # Celery app + beat schedule: etl.collect_supervision (every ETL_COLLECT_INTERVAL_S),
    │                             #   etl.refresh_kpi_view (daily 02:00), etl.generate_monthly_report (1st of month, 02:30)
    ├── config.py                 # DB DSN / broker URL / API URL / REPORTS_DIR helpers (+ netxms_dsn for the geography rebuild)
    ├── pipelines/                # collector.py (loads active nodes), tasks.py (the Celery tasks),
    │                             #   status.py (publishes each pass's per-tool outcome to Redis)
    ├── extract/                  # Real per-tool collectors: Zabbix JSON-RPC, Nagios statusjson, NetXMS REST,
    │                             #   Centreon REST v2, iTop REST (core/get) + common.py (node matching)
    ├── transform/                # normalize.py (ingest payload shape) + causes.py (cause taxonomy & classifier)
    ├── load/                     # Posts incidents to /api/incidents/ingest{,/bulk}; downloads monthly reports
    ├── provision_netxms_nodes.py # One-off: create dim_node rows from the NetXMS inventory
    ├── provision_itop_nodes.py   # One-off: create dim_node rows from iTop's open tickets
    └── rebuild_geography.py      # One-off: swap the seeded dimensions for the real ANPTIC reference data
```

The three one-off scripts are dry-run by default and take `--apply` to write —
see [Loading the real CMDB](#loading-the-real-cmdb).

Two containers run this image: `etl-beat` (Celery scheduler) and `etl-worker`
(Celery worker) — see [docs/architecture.md](docs/architecture.md).

---

## Getting Started

### 1. Clone the Repository

```bash
git clone <repository-url>
cd noc
```

### 2. Configure Environment Variables

`.env` is gitignored, so a fresh clone has none — copy the template and edit the
values to match your environment before running:

```bash
cp .env.example .env
nano .env
```

Key variables to configure:

```env
# ── Database ─────────────────────────────────────────────
POSTGRES_USER=noc_db_user
POSTGRES_PASSWORD=your_secure_password   # ⚠️ Change this in production!
POSTGRES_DB=noc_db
POSTGRES_HOST=postgres
POSTGRES_PORT=5432

# ── Redis Cache ──────────────────────────────────────────
REDIS_HOST=redis
REDIS_PORT=6379
CACHE_TTL=300                            # Cache duration in seconds

# ── Security ─────────────────────────────────────────────
SECRET_KEY=your_secret_key               # ⚠️ Change this in production!
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# ── Monitoring Tool Integrations ─────────────────────────
# All five tools run as containers in this same compose stack — these defaults
# point at them over the compose network. Swap in external hosts (e.g.
# https://zabbix.anptic.bf/...) to poll real servers instead. A collector runs
# only when its *_API_URL is set; clear one to disable that tool.
ZABBIX_API_URL=http://zabbix-web:8080/api_jsonrpc.php
ZABBIX_USER=Admin
ZABBIX_PASSWORD=zabbix
ZABBIX_API_TOKEN=                        # Zabbix >= 5.4 token; alternative to user/password

NAGIOS_API_URL=http://nagios
NAGIOS_USER=nagiosadmin                  # Also the Nagios container's web login
NAGIOS_PASSWORD=your_nagios_password
NAGIOS_API_KEY=                          # Sent as X-Auth-Token if set

# NetXMS Web API (REST v1) — the collector's endpoint, not the console.
NETXMS_API_URL=http://netxms:8000
NETXMS_USER=admin
NETXMS_PASSWORD=your_netxms_password

# Local Centreon central (UI http://localhost:8084/centreon). CENTREON_PASSWORD
# is applied to its "admin" account on first start and must satisfy Centreon's
# password policy (12+ chars, lower/upper/digit and one of @$!%*?&).
CENTREON_API_URL=http://centreon/centreon/api/latest
CENTREON_USER=admin
CENTREON_PASSWORD=your_centreon_password
CENTREON_API_KEY=

# iTop REST/JSON API — read-only core/get on class Incident. Empty by default:
# the bundled iTop needs its one-time setup (and the REST Services User
# profile) before the API answers anything but HTTP 500. Note the API lives at
# a query-string-versioned URL, not a bare host.
ITOP_API_URL=                            # e.g. http://itop/webservices/rest.php?version=1.0
ITOP_USER=
ITOP_PASSWORD=

# ── NetXMS database ──────────────────────────────────────
# Used by the netxms-db container, and read directly by
# etl/rebuild_geography.py — the ANPTIC administrative reference tables
# (donnebase) are not exposed by the NetXMS REST API. Collectors do not use it.
NETXMS_DB_NAME=netxms
NETXMS_DB_USER=netxms
NETXMS_DB_PASSWORD=your_netxms_db_password

# ── Webhook auth ─────────────────────────────────────────
# Static bearer key supervision tools (Centreon/Zabbix) must send when
# calling POST /api/incidents/ingest — Authorization: Bearer $NOC_API_KEY
NOC_API_KEY=your_webhook_api_key

# ── Notifications (SMS/email on critical incidents) ──────
NOTIFICATIONS_ENABLED=false              # Flip to true once Twilio/SMTP are configured
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_FROM_NUMBER=
NOC_SMS_RECIPIENTS=+22670000000          # Comma-separated
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=noc@anptic.bf
NOC_EMAIL_RECIPIENTS=noc@anptic.bf       # Comma-separated

# ── Web Push (browser/PWA push on critical incidents) ────
# Generate a keypair per environment — never reuse the demo one in production
# (see docs/integrations.md).
VAPID_PUBLIC_KEY=
VAPID_PRIVATE_KEY=
VAPID_CLAIMS_EMAIL=noc@anptic.bf

# ── Rate limiting (per IP, per minute) ──────────────────
RATE_LIMIT_ENABLED=true
RATE_LIMIT_READ_PER_MIN=100
RATE_LIMIT_INGEST_PER_MIN=10

# ── Materialized view refresh ────────────────────────────
# true (demo): refresh mv_kpi_node_monthly on every write, keeps small datasets
# interactive. false (production): rely on the nightly 02:00 ETL refresh only.
SYNC_MV_REFRESH=true

# ── ETL ──────────────────────────────────────────────────
CELERY_BROKER_DB=1                       # Redis DB index used as the Celery broker
ETL_COLLECT_INTERVAL_S=300               # Seconds between collection passes
```

`.env.example` is the authoritative, fully commented template — it carries a
few settings this walkthrough skips (the bundled tools' own DB passwords,
`CORS_ORIGINS`, `DASHBOARD_URL`, Twilio API-key auth, log level). Start from it:

```bash
cp .env.example .env
```

> **⚠️ Security Note:** The `.env` file is listed in `.gitignore`. Never commit real credentials to source control. For production, use a secrets manager.

---

### 3. Run with Docker (Recommended)

This is the **easiest and recommended** method. Docker Compose will build and start all services automatically.

#### Build and Start All Services

```bash
# From the project root directory
docker-compose up --build
```

To run in **detached (background) mode**:

```bash
docker-compose up --build -d
```

#### Check Service Status

```bash
docker-compose ps
```

#### View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f backend
docker-compose logs -f frontend
docker-compose logs -f postgres
```

#### Stop All Services

```bash
docker-compose down
```

To also **remove volumes** (⚠️ this deletes all database data):

```bash
docker-compose down -v
```

#### Rebuild a Single Service

```bash
docker-compose up --build backend
docker-compose up --build frontend
```

---

### 4. Run Locally (Development)

If you prefer to develop without Docker, you can run each component separately.

#### 4a. Start Required Infrastructure

You still need PostgreSQL and Redis running. The easiest way is to start only those services via Docker:

```bash
docker-compose up -d postgres redis
```

#### 4b. Backend (FastAPI)

```bash
cd backend

# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate          # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Update .env to use localhost for local dev
# DB_HOST=localhost, REDIS_HOST=localhost

# Start the development server (with hot-reload)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

#### 4c. Frontend (React + Vite)

```bash
cd frontend

# Install Node.js dependencies
npm install

# Start the Vite development server (with HMR)
npm run dev
```

The dev server starts at `http://localhost:5173` by default.

#### 4d. Other Frontend Commands

```bash
# Lint the codebase
npm run lint

# Build for production
npm run build

# Preview the production build
npm run preview
```

---

## Services & Ports

After starting the project, the following services are available:

| Service | URL | Description |
|---|---|---|
| **Application (via NGINX, HTTPS)** | https://localhost:8443 | **Main entry point** — self-signed cert, browser will warn |
| **Application (via NGINX, HTTP)** | http://localhost:8888 | Redirects (301) to the HTTPS URL above |
| **Zabbix** | http://localhost:8081 | Bundled Zabbix 7.0 UI — default login `Admin` / `zabbix` |
| **iTop** | http://localhost:8082 | Bundled iTop 3.2 (ITSM/CMDB) — one-time setup on first start, see below |
| **Nagios** | http://localhost:8083 | Bundled Nagios Core — login `$NAGIOS_USER` / `$NAGIOS_PASSWORD` |
| **Centreon** | http://localhost:8084 | Bundled Centreon central UI — login `admin` / `$CENTREON_PASSWORD` |
| **NetXMS Web API** | http://localhost:8085 | REST v1 — what the collector polls (`admin` / `$NETXMS_PASSWORD`) |
| **NetXMS web console** | http://localhost:8086 | Bundled NetXMS console (`admin` / `$NETXMS_PASSWORD`) |
| **PostgreSQL (app)** | `localhost:5436` | The dashboard's own database, for `psql`/BI access |
| **PostgreSQL (NetXMS)** | `localhost:5438` | NetXMS's database — the `donnebase` reference schema lives here |

**The frontend and backend are not published on the host.** The frontend
container serves its production build over its own nginx on port 80 inside the
compose network, and the backend publishes `8000` without a fixed host port —
both are reachable only through the NGINX gateway, which is what makes HTTPS
unavoidable rather than optional. `/api/` and `/ws/` are proxied; everything
else falls through to the SPA.

FastAPI's interactive docs are **not** proxied (`/docs` and `/redoc` are not
under `/api/`), so reach them on the backend's ephemeral host port:

```bash
docker compose port backend 8000        # e.g. 0.0.0.0:49157
xdg-open "http://localhost:49157/docs"
```

Running the backend directly (`uvicorn`, see [Run Locally](#4-run-locally-development))
puts them back at http://localhost:8000/docs and `/redoc`.

### First-run setup of the bundled tools

**iTop** ships uninstalled and its REST API stays unavailable until setup
completes. Run it once, either through the wizard at http://localhost:8082 or
unattended:

```bash
docker compose exec -u www-data -w /var/www/html/setup/unattended-install itop \
  php unattended-install.php --param-file=/path/to/response.xml \
  --installation_xml=/var/www/html/datamodels/2.x/installation.xml
```

Three requirements for that command to produce a usable instance:

1. **Pass `--installation_xml`.** The response file's `selected_extensions` is
   only honoured when it is present.
2. **Select the ITIL module set** (`itop-ticket-mgmt-itil-incident`). The
   collector queries the `Incident` class, which exists only there — the
   non-ITIL default provides `UserRequest` only.
3. **Start from a clean state.** If an earlier run left `data/.maintenance` or
   `data/.readonly` behind, delete both before re-running.

Then grant the API user iTop's **REST Services User** profile.
`secure_rest_services` is enabled by default and Administrator does not imply
it, so the profile has to be assigned explicitly.

**NetXMS** uses a PostGIS-enabled database image
(`postgis/postgis:15-3.5-alpine`, a drop-in for `postgres:15` on the same
PGDATA). The ANPTIC reference data carries geometry columns that need the
extension — see
[Restoring the production NetXMS dump](#restoring-the-production-netxms-dump).

### HTTPS / TLS

The NGINX gateway terminates TLS with a **self-signed certificate**, generated by `nginx/generate_cert.sh` into `nginx/certs/` (gitignored — never commit private keys). Because it's self-signed, browsers and `curl` will flag it as untrusted:

```bash
# Browser: click through the "not secure" warning (expected for self-signed certs)
curl -k https://localhost:8443/api/kpi/summary?month=7&year=2026   # -k skips cert verification
```

To regenerate the certificate (e.g. after its ~825-day validity expires, or to add another SAN entry):

```bash
./nginx/generate_cert.sh
docker compose restart nginx
```

For a real deployment, replace `nginx/certs/*` with a certificate from Let's Encrypt or ANPTIC's internal CA — the generated cert's CN/SAN already match the production domains referenced elsewhere in this README (`noc.anptic.bf`, `noc-api.anptic.bf`).

---

## Supervision Map

The **Carte**, "Vue Globale" and "Vue par Localité" tabs all render a real **Leaflet + OpenStreetMap** map of Burkina Faso (`frontend/src/components/map/BurkinaFasoMap.jsx`), fed by `GET /api/kpi/localities/map` (every locality with coordinates, incident count, and availability for the selected month — unlike `/api/kpi/localities`, this one includes localities with zero incidents so the map never has "missing" nodes).

- **Markers**: colored by availability (green ≥97%, amber 90–97%, red <90%), sized by incident volume (`sqrt` scale), with a pulsing ring on critical ones. Hover for a tooltip, click to select.
- **Dark mode**: OSM only publishes one (light) cartography, so dark mode applies a CSS filter (`invert + hue-rotate + contrast`) scoped to just the tile pane in `index.css` (`.leaflet-dark-map .leaflet-tile-pane`) — markers/popups are on a separate pane and stay unaffected.
- **Stacking**: the map wrapper uses `isolate z-0` so Leaflet's internal z-indexes (up to 1000) can't paint over the sticky header/tab bar while scrolling.
- **Sizing**: the map fills its card and holds a `MIN_HEIGHT` floor of 280px. Set that floor as **`min-height`, never `height`** — the wrapper is a flex item with `flex-1` (`flex-basis: 0%`), which takes precedence over `height`. Host pages carry matching row floors (`min-h-[380px]` on Vue Globale, `min-h-[520px]` on Vue par Localité, which stacks the map *and* the locality list); keep them in step with `MIN_HEIGHT`, since `Card` does not clip its content.
- **Resize handling**: Leaflet measures its container at mount and then tracks only **window** resizes, so an `InvalidateOnResize` child watches the container with a `ResizeObserver` and calls `map.invalidateSize()` (rAF-coalesced) whenever the card itself reflows.
- **Attribution**: the default "Leaflet | © OpenStreetMap" control is disabled (`attributionControl={false}`) for a cleaner internal-dashboard look. ⚠️ Tiles still come from the free `tile.openstreetmap.org` servers, whose [usage policy](https://operations.osmfoundation.org/policies/tiles/) requires visible attribution — restore the credit or switch to a self-hosted/commercial tile provider before any public deployment.
- **Scroll-zoom gating**: the map requires one click before the scroll wheel zooms it (with a fading hint chip), so scrolling the dashboard page over the map doesn't get hijacked into zooming it — a standard embedded-map pattern.
- **Bounded**: `maxBounds`/`minZoom`/`maxZoom` keep panning/zooming scoped to Burkina Faso.
- **`LocalityBulletList`** (the panel next to the map) is the same data as a plain clickable list — a table-view/keyboard-accessible companion to the map, not just decoration.
- **Cross-page navigation**: clicking a marker or bullet in "Vue Globale" calls `navigate('/locality', { state: { localityId } })`; `LocalityView` reads that state to preselect the clicked locality (falling back to the busiest one if navigated to directly via the tab).

### The Carte tab

`frontend/src/pages/MapView.jsx` gives the map a page of its own, with the two
things it cannot carry as a panel beside KPI cards: filters, and a
click-through list of what is actually broken.

- **Markers are sized by the incidents matching the filter**, not by the
  locality's monthly total, and a locality with nothing matching is removed
  rather than drawn at zero.
- **Severity chips and a region select**, both applied client-side. That is
  why `/api/kpi/localities/map` also returns a `by_severity` breakdown
  (`{critical, high, medium, low}`, omitting severities with no incidents) per
  locality — filtering becomes a sum over data already in hand instead of a
  request per toggle.
- **Those counts are month-scoped**, like every other figure the payload
  carries, so the period picker drives this page the way it drives the rest of
  the dashboard. Keep any new figure added to this payload month-scoped too.
- **Clicking a locality lists its own open incidents** — node code,
  description, severity and age. `GET /api/alerts/open` takes a `locality_id`
  for this: the unfiltered feed is a top-N across the whole network, and with
  ~1450 incidents open a given town's alerts would almost never surface in it.

The panel names both numbers it knows — *"79 affiché(s) · 159 au total"* —
because they count genuinely different things and it would be dishonest to show
only one. The first is the list: the oldest 100 **currently open** alerts the
API will return for that locality, filtered by severity in the browser. The
second is the marker's own count: the locality's incidents **detected this
month** matching the same severity filter. They diverge whenever a locality has
more than 100 open incidents, or when the month's incidents have since been
resolved — and the second number is what tells you the list is not the whole
story.

The selected locality is derived from the filtered set rather than stored, so
the panel can never contradict the marker it came from when the filter
changes. A selection that gets filtered out closes the panel.

---

## Authentication

The dashboard is gated behind a login screen (`/login`) with two methods, both
issuing the same JWT (`dim_user` table, `backend/app/services/auth_service.py`):

- **Username + password** — bcrypt-hashed.
- **PIN quick login** — a 4-digit code, SHA-256 hashed for fast direct lookup
  (a short PIN doesn't warrant adaptive hashing, and needs to support lookup
  by hash rather than iterating every user).

Demo accounts (seeded by `database/generate_seed.py`):

| Username | Password | PIN | Role |
|---|---|---|---|
| `admin` | `admin123` | `1234` | admin |
| `analyst` | `analyst123` | `2222` | analyst |
| `noc_agent` | `noc123` | `3333` | noc_agent |

The frontend stores the JWT in `localStorage` (zustand `persist`, see
`frontend/src/store/auth.js`) and attaches it to every API call via an axios
request interceptor; a 401 response anywhere logs the session out and the login
screen explains why ("Session expirée") rather than appearing unprompted.

**The session slides.** The token lives `ACCESS_TOKEN_EXPIRE_MINUTES` (default
30), and `frontend/src/hooks/useSessionKeepAlive.js` exchanges it for a fresh
one via `POST /api/auth/refresh` once it is within 5 minutes of expiring —
checked every minute and whenever the tab becomes visible again, since a
backgrounded tab throttles timers hard enough to let a session lapse unnoticed.
A dashboard someone is watching stays logged in; one left unattended still
lapses 30 minutes after the last activity.

Renewal deliberately runs off the access token itself rather than a separate
long-lived refresh token: an already-expired session cannot be revived, which
is the intended end state for an abandoned console. Raising
`ACCESS_TOKEN_EXPIRE_MINUTES` instead would buy the same convenience by leaving
a long-lived bearer token sitting in `localStorage`.

**Every endpoint requires authentication**: read endpoints
(KPI/SLA/alerts/report) accept any logged-in user's JWT, the ingest webhook
uses the static `NOC_API_KEY`, and roles gate the write actions:

| Role | Read dashboards | Acknowledge | Resolve |
|---|---|---|---|
| `admin` | ✅ | ✅ | ✅ |
| `noc_agent` | ✅ | ✅ | ✅ |
| `analyst` | ✅ | ❌ (403) | ❌ (403) |

The frontend mirrors this: analysts don't see the acknowledge button in the
alert feed. Enforcement lives in `require_role()`
(`backend/app/core/security.py`). `/api/report/monthly` additionally accepts
the static API key so the scheduled ETL export can pull it without a user
session. Endpoints are also rate-limited per IP (100/min reads, 10/min ingest
— HTTP 429 beyond that).

---

## Branding: Logo & Favicon

The app logo (`frontend/src/assets/images/noc-logo.png`) is the brand master asset: a navy-and-signal-blue mark (location pin + radio/signal waves) matching the dashboard's dark-first palette. It's used directly in the `Header` and `Login` page, and derived into the full browser favicon set.

The source PNG shipped with a plain white canvas around a rounded-square mark (no alpha channel) — unusable as-is on a dark header, since the white corners would show as a halo. A one-off Pillow script cleaned it up and derived every size the app needs; **the results are checked in, and the script is not** (it needed Pillow to run, which nothing else in the repo does). What it produced, and what you'd have to reproduce by hand for a new logo:

- The 4 corners masked transparent using a **geometric rounded-rect mask**, not color-keying — the mark itself has white accents (the signal-gap bar) that color-keying on "near white" would incorrectly erase.
- The cleaned master (`frontend/src/assets/images/noc-logo.png`, transparent corners) plus the light `noc-logo-256.png` actually imported by the UI (the raw master is 1254px/1.2MB — far more than a ~56px header icon needs; 256px covers retina displays at that size for ~70KB).
- The favicon set, flattened onto the brand navy (`#0b1220`) since transparency reads worse than a solid tab-color background at 16–32px: `favicon.ico` (multi-size), `favicon-16x16.png`, `favicon-32x32.png`, `apple-touch-icon.png` (180px), `icon-192.png`, `icon-512.png` — all in `frontend/public/`, linked from `frontend/index.html` and referenced by the PWA manifest.

---

## Integrations

The dashboard integrates with the following monitoring systems via API or webhook:

| System | Protocol | What the collector reads |
|---|---|---|
| **Zabbix** | JSON-RPC (`problem.get`) | Currently active problems |
| **Nagios** | `statusjson.cgi` | Hosts/services in a non-OK state |
| **NetXMS** | REST v1 (`/v1/alarms`) | Active alarms |
| **Centreon** | REST v2 (`/monitoring/resources`) | Resources in a problem state |
| **iTop** | REST/JSON (`core/get` on `Incident`) | Still-active tickets — **read-only, permanently** |

All five are polled by the same ETL pass and land in `fact_incident` through
`/api/incidents/ingest/bulk`; `fact_incident.source_tool` records which one
raised each incident, which is what the Interopérabilité tab groups on.

iTop is the odd one out: it is the **service desk of record**, not a probe. The
collector never creates, updates or closes a ticket, and that is a standing
design constraint rather than an unfinished feature — anything that writes back
belongs on the iTop side, where the ITSM workflow, its approvals and its audit
trail live. It also matches tickets against the **whole** node list rather than
one tool's subset, since a ticket can reference any CI. Resolved and closed
tickets are excluded from the fetch, not merely ignored: ingestion always writes
`status="open"`, so a resolved ticket would otherwise reappear as a brand-new
incident.

Configure integration URLs and credentials in the `.env` file as described in the [Environment Variables](#2-configure-environment-variables) section. See [docs/integrations.md](docs/integrations.md) for details.

---

## Progressive Web App & Push Notifications

The frontend builds as an installable PWA (`vite-plugin-pwa`, `injectManifest`
strategy — `frontend/src/sw.js`, registered from `main.jsx`): it precaches the
app shell for offline use and also carries a real **Web Push** implementation,
not just an in-app toast.

- **Bell toggle** in the header (next to the theme switch) requests
  `Notification` permission and subscribes via the browser's Push API
  (`usePushNotifications.js`); the subscription (`endpoint` + encryption keys)
  is registered with the backend at `POST /api/notifications/subscribe`.
- On a **critical** incident, `backend/app/services/push_service.py` sends a
  VAPID-signed push to every subscribed device, alongside the existing
  SMS/email notifications — same fail-safe pattern (delivery failures are
  logged, never block ingestion; a `404`/`410` response means the browser
  dropped the subscription, so it's pruned automatically).
- Requires a **VAPID keypair** (`VAPID_PUBLIC_KEY`/`VAPID_PRIVATE_KEY` in
  `.env`) — see [docs/integrations.md](docs/integrations.md#web-push-browserpwa)
  for how to generate one. The demo keypair shipped in `.env` is for local use
  only; generate a fresh one per real deployment.
- Clicking a delivered notification (`sw.js`'s `notificationclick` handler)
  focuses an already-open dashboard tab or opens a new one.

---

## API Documentation

FastAPI generates interactive documentation from the routers themselves:

- **Swagger UI**: `/docs`
- **ReDoc**: `/redoc`

Neither is proxied by NGINX (they don't live under `/api/`) — in the Docker
stack, find the backend's host port with `docker compose port backend 8000`;
running uvicorn locally they're at http://localhost:8000/docs. For a written
reference that doesn't need the app running, see
[docs/api-reference.md](docs/api-reference.md).

Key endpoints (all read endpoints take `month`/`year` query params and
require a JWT; see [Authentication](#authentication) for roles and rate limits):

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/kpi/summary` | Monthly KPI summary + delta vs. previous month |
| GET | `/api/kpi/compare` | Current month vs N-1 and N-3 months, with per-KPI deltas |
| GET | `/api/kpi/localities` | Top localities by incident count |
| GET | `/api/kpi/nodes` | Top nodes (optionally filtered by `locality_id`) |
| GET | `/api/kpi/recurrent` | Nodes with ≥ `min_count` incidents |
| GET | `/api/kpi/trend` | Last N months of incidents/availability |
| GET | `/api/kpi/hour-distribution` | Incidents per hour of day (H24) |
| GET | `/api/kpi/causes` | Incident breakdown by cause category |
| GET | `/api/sla` | SLA indicators vs. targets |
| GET | `/api/alerts/open` | Open/acknowledged alerts, oldest first (optional `locality_id` filter) |
| GET | `/api/locality/{id}/nodes` | Node detail for one locality |
| GET | `/api/kpi/localities/map` | Every locality with coordinates + KPIs, plus a month-scoped `by_severity` breakdown for the Carte tab |
| GET | `/api/interop/status` | Live state of each supervision-tool collector + incidents raised per tool |
| POST | `/api/incidents/ingest` | Webhook ingestion, one incident (requires `Authorization: Bearer $NOC_API_KEY`) |
| POST | `/api/incidents/ingest/bulk` | Batch ingestion — a poller's whole active set in one call (same API key) |
| PATCH | `/api/incidents/{id}/acknowledge` | Mark acknowledged (roles: `admin`, `noc_agent`) |
| PATCH | `/api/incidents/{id}/resolve` | Resolve an incident (roles: `admin`, `noc_agent`) |
| GET | `/api/report/monthly` | Monthly report, `format=json`, `pdf` or `docx` (JWT **or** API key) |
| POST | `/api/auth/login` | Username/password login → JWT + `expires_in` |
| POST | `/api/auth/pin-login` | 4-digit PIN quick login → JWT + `expires_in` |
| POST | `/api/auth/refresh` | Exchange a still-valid JWT for a fresh one (sliding session) |
| GET | `/api/auth/me` | Current user (session restore) |
| GET | `/api/notifications/vapid-public-key` | The server's VAPID public key (frontend uses it as `applicationServerKey`) |
| POST | `/api/notifications/subscribe` | Register this device's Web Push subscription for the current user |
| DELETE | `/api/notifications/subscribe` | Remove a Web Push subscription (by `endpoint`) |
| WS | `/ws/alerts?token=<JWT>` | Real-time incident stream (Redis pub/sub behind the scenes) |

New incidents are also **pushed live** to the dashboard: ingest publishes to
Redis, `/ws/alerts` forwards to every connected browser, and the frontend
(`useRealtime.js`) refreshes its alert/KPI queries on each message — with 15s
polling kept as a fallback. Critical-severity incidents additionally trigger
SMS + email (`backend/app/services/notification_service.py`, when
`NOTIFICATIONS_ENABLED=true`) and a real browser Web Push notification to every
subscribed device (`backend/app/services/push_service.py`, when
`VAPID_PUBLIC_KEY`/`VAPID_PRIVATE_KEY` are set — see
[Progressive Web App & Push Notifications](#progressive-web-app--push-notifications)).

### `/ingest` vs `/ingest/bulk`

The two ingestion paths differ in more than batching, and picking the wrong one
is consequential:

| | `/ingest` | `/ingest/bulk` |
|---|---|---|
| Payload | one incident | the poller's **whole** active set |
| Rate-limit cost | 1 unit per incident | 1 unit per batch |
| Broadcast / SMS / email / push | **yes** | **no** |
| Missing alerts | ignored | **resolved** (treated as recovered) |

`/ingest` is for webhooks — a single event that has just happened and may need
to reach a human. `/ingest/bulk` is for a collector reconciling state: it is a
snapshot, so anything absent from it is closed (see
[Incident lifecycle](#incident-lifecycle)), and it deliberately notifies nobody.
NetXMS alone reports ~1450 active alarms per pass, ~1000 of them critical —
sending those one at a time would exhaust the 10/min ingest quota in the first
six and page the permanence a thousand times for a backlog it already knows
about.

> ⚠️ **Post partial batches to `/ingest/bulk` and you will resolve incidents
> that are still live.** Only send a complete active set.

---

## Demo Data & ETL Collection

The database ships with a generated demo dataset so the dashboard is fully interactive out of the box — no real Zabbix/Nagios/Centreon/iTop instance required:

- **13 regions**, **14 localities**, **~157 nodes** across Burkina Faso, **6 months of incidents**, and the 3 demo user accounts (see [Authentication](#authentication)) — all in `database/02_seed.sql`, produced by `database/generate_seed.py`.

> **Running against real data?** The demo dimensions are fictional and sit in
> the same tables as anything you collect. `etl/rebuild_geography.py` replaces
> them with the real ANPTIC reference data and deletes the demo facts — see
> [Loading the real CMDB](#loading-the-real-cmdb).
- On a **fresh** Postgres volume, `01_schema.sql` then `02_seed.sql` run automatically via `docker-entrypoint-initdb.d`. To regenerate the dataset or force a reseed:
  ```bash
  python3 database/generate_seed.py   # rewrites database/02_seed.sql
  docker compose down
  docker volume rm noc_pgdata         # drops the existing DB so init scripts re-run
  docker compose up -d
  ```
- The **`etl` service** runs **real collectors** (no simulation): every `ETL_COLLECT_INTERVAL_S` (default 5 min) it polls each supervision tool whose `*_API_URL` is configured — Zabbix (JSON-RPC `problem.get`), Nagios (`statusjson.cgi`), NetXMS (REST alarms), Centreon (REST v2 resources), iTop (REST `core/get` on active `Incident` tickets) — maps each alert onto a `dim_node` (by code, then name, then IP), and POSTs the whole pass to `/api/incidents/ingest/bulk` in **one request per tool**. Tools without an endpoint are skipped; one unreachable tool never blocks the others. Re-reported still-open alerts are deduplicated on `(source_tool, external_id)`, and alerts the tool has stopped reporting are resolved — see [Incident lifecycle](#incident-lifecycle). **To integrate: just set the tool's `*_API_URL` + credentials in `.env` and restart `etl-worker`** — see [docs/integrations.md](docs/integrations.md).
- **Alarm-source identity is cached across polls** (`NETXMS_OBJECT_CACHE_TTL_S`, default 24h, in Redis). NetXMS's `/v1/objects` lists only root containers, so each distinct alarm source otherwise costs its own HTTP request *every* pass — ~1180 per poll on the ANPTIC instance. With the cache a steady-state pass makes **4** requests instead of 1173. See [docs/integrations.md](docs/integrations.md).
- **Not every alert is a host.** On the ANPTIC NetXMS instance roughly one alarm source in eight is a `BusinessService` rather than a `Node`; those are skipped silently (`HOST_CLASSES` in `etl/extract/netxms.py`) instead of being reported as unprovisioned hosts on every pass.
- **Causes are classified from the alert text** (`etl/transform/causes.py`): the taxonomy is what the tools actually observe — "Nœud injoignable (ICMP)", "Interface hors service" — not root cause, which belongs on the iTop ticket where a human owns it. Text nothing matches stays uncategorised rather than being forced into an "Autre" bucket that would quietly become the largest cause on the dashboard.
- The same Celery beat also runs two **scheduled jobs**:
  - `etl.refresh_kpi_view` — nightly at **02:00**, `REFRESH MATERIALIZED VIEW CONCURRENTLY mv_kpi_node_monthly`.
  - `etl.generate_monthly_report` — on the **1st of each month at 02:30**, downloads the previous month's report (PDF + DOCX) and archives it in the `reports` Docker volume (`/reports` inside `etl-worker`).
- Every pass records its own outcome. The worker writes the per-tool result to a Redis key with a TTL of three intervals, and `GET /api/interop/status` serves it to the **Interopérabilité** tab — see [Collector status](#collector-status).

---

## Restoring the production NetXMS dump

Everything in [Loading the real CMDB](#loading-the-real-cmdb) reads from the
NetXMS database: the node inventory, and the `donnebase` administrative
reference tables that give localities their coordinates. Both arrive in one
place — a plain-SQL `pg_dump` of the ANPTIC production server
(`netxmsbd07082026.sql`, 356 MB, taken 2026-08-07 from PostgreSQL 16.1).

**Restore it with the script, not by hand:**

```bash
./database/restore_netxms_dump.sh --dry-run     # preflight only, changes nothing
./database/restore_netxms_dump.sh               # restore into an empty netxms DB
./database/restore_netxms_dump.sh --force       # drop an existing netxms DB first
```

It reads `NETXMS_DB_*` from `.env`, targets `localhost:5438` (the `netxms-db`
container), and exits non-zero on any error the dump raises. Options:
`--dry-run`, `--force`, `--keep-timescale-triggers`, and the usual
`-h/-p/-U/-d`.

> ⚠️ **This is the NetXMS database on port 5438, not the dashboard's own
> database on 5436.** They are different containers with different content;
> `--force` against the wrong one destroys the NOC dataset.

### What the restore requires

The dump is not self-contained. Four things have to be arranged around it, all
of which the script does for you:

| # | Requirement | Detail | Handled by |
|---|---|---|---|
| 1 | **Five roles exist** | The dump assigns ownership to `postgres`, `netxmsu`, `siganptic`, `dev` and grants to `arm`, but contains no `CREATE ROLE` | Created `NOLOGIN` and passwordless — they exist to own objects, not to log in |
| 2 | **PostGIS installed first** | Columns are declared `public.geometry(Point,4326)` and the dump's `search_path` is empty, so the type must resolve under exactly that name | `CREATE EXTENSION postgis` into `public`, before the restore |
| 3 | **`CREATE SCHEMA public` removed** | Requirement 2 needs the stock `public` schema kept, so the dump's own copy of that statement is dropped | One `sed` filter |
| 4 | **TimescaleDB triggers removed** | 21 tables carry a `ts_insert_blocker` trigger calling `_timescaledb_functions.insert_blocker()`; TimescaleDB is not in `postgis/postgis:15-3.5-alpine` | A second `sed` filter — those tables restore as plain PostgreSQL tables |

Both filters are anchored to the exact statement text `pg_dump` emits at the
start of a line, so no `COPY` data row is affected. Everything else runs under
`ON_ERROR_STOP=1`: **if the script reports success, the whole dump applied.**

**Restore into an empty database.** `psql` applies a plain-SQL dump statement by
statement without stopping, so every `COPY` appends its rows to whatever the
target already holds. Use `--force` to drop and recreate, or `-d` to point at a
fresh database name; the script checks the target and stops before writing
anything if it is already populated.

To preview what the dump would do to a populated database without changing it,
run it in a transaction that rolls back:

```bash
psql -U netxms -h localhost -p 5438 --single-transaction -v ON_ERROR_STOP=1 \
  -f netxmsbd07082026.sql
```

### What you get, and what you don't

- ✅ **1407 nodes**, their `object_properties`, and the full NetXMS
  configuration — the inventory `provision_netxms_nodes.py` reads.
- ✅ **The `donnebase` reference schema** — 488 villes, communes, provinces and
  the region geometries `rebuild_geography.py` resolves addresses through.
- ❌ **No time-series history.** `event_log`, `syslog`, `snmp_trap_log` and
  every `idata_sc_*` / `tdata_sc_*` table are TimescaleDB hypertables in
  production. Their rows live in chunks under `_timescaledb_internal`, which
  `pg_dump` did not include, so they restore **structurally empty** — the
  `COPY public.event_log … FROM stdin;` in the file is followed immediately by
  its terminator. Availability KPIs computed against this server accumulate
  from the restore forward, not from the dump's date.
- ❌ **No extensions** beyond the PostGIS the script installs.
- ⚠️ **Production credentials.** The dump carries `public.users` — real named
  ANPTIC accounts and their password hashes. After restoring, `NETXMS_PASSWORD`
  from `.env` no longer opens the console: the `admin` account is production's.
  Keep port 5438 bound to localhost and treat the database as sensitive.

### Restoring by hand

If you need to do it manually — a different target, or a partial restore:

```bash
set -a; source .env; set +a
export PGPASSWORD="$NETXMS_DB_PASSWORD"
PSQL="psql -h localhost -p 5438 -U $NETXMS_DB_USER"

# 1. Roles the dump assigns objects to (NOLOGIN — ownership only)
for r in postgres netxmsu siganptic dev arm; do
  $PSQL -d postgres -c "CREATE ROLE $r NOLOGIN" 2>/dev/null || true
done

# 2. A fresh database with PostGIS in its public schema
$PSQL -d postgres -c "DROP DATABASE IF EXISTS netxms"
$PSQL -d postgres -c "CREATE DATABASE netxms OWNER $NETXMS_DB_USER ENCODING 'UTF8'"
$PSQL -d netxms   -c "CREATE EXTENSION postgis"

# 3. Restore, stripping the two families of statement this server cannot run
sed -e '/^CREATE SCHEMA public;$/d' \
    -e '/^CREATE TRIGGER ts_insert_blocker .*insert_blocker();$/d' \
    netxmsbd07082026.sql \
  | $PSQL -d netxms -v ON_ERROR_STOP=1 --quiet -o /dev/null -f -
```

Restore without `--single-transaction`: at 356 MB it would hold locks and WAL
for the whole run. To start over, drop the database and repeat step 2. Keep
that flag for the read-only trial run shown above.

### Verify

```bash
psql -h localhost -p 5438 -U netxms -d netxms -c "
  select (select count(*) from public.nodes)            as nodes,
         (select count(*) from donnebase.ville)         as villes,
         (select count(*) from donnebase.limiteregion)  as regions,
         pg_size_pretty(pg_database_size('netxms'))     as size"
```

A healthy restore reports roughly **1407 nodes**, **488 villes**, and about
**1.3 GB**. The script prints the same figures automatically, plus an `ABSENT`
marker for any expected table the dump did not contain.

### Checklist

Confirm all of these before restoring — `--dry-run` verifies the first four:

- [ ] `netxms-db` is running and reachable on `localhost:5438`
- [ ] The connecting role is a **superuser** (`netxms` is, in this stack) — the
      dump reassigns ownership to other roles
- [ ] The server image provides **PostGIS** (`postgis/postgis:15-3.5-alpine`)
- [ ] At least **3× the dump size free on disk** (~1.1 GB for a 356 MB dump;
      the restore settles around 1.3 GB once indexes are built)
- [ ] The target database is **empty**, or you intend `--force`

Once it's in, continue with [Loading the real CMDB](#loading-the-real-cmdb).

> The dump file itself is **not in version control** — 356 MB of production
> data, including credentials, does not belong in the repo. Keep it out of
> commits (add `*.sql` at the root to `.gitignore`, or store it outside the
> working tree) and transfer it out of band.

---

## Loading the real CMDB

Collectors match each alert to a `dim_node` by code, name or IP, so **the CMDB
must hold the real hosts before a real supervision tool can ingest anything** —
the seeded nodes are fictional and share no names with real infrastructure.
Three scripts populate it. All live in `etl/` and run inside the worker:

| Script | What it does |
|---|---|
| `provision_netxms_nodes.py` | Creates `dim_node` rows for every host in the NetXMS inventory |
| `provision_itop_nodes.py` | Same, for the hosts iTop's open tickets reference |
| `rebuild_geography.py` | Replaces the seeded regions/localities/causes with the real reference data and deletes the demo facts |

```bash
# Dry run first — both print the full plan and change nothing
docker compose exec etl-worker python provision_netxms_nodes.py
docker compose exec etl-worker python provision_netxms_nodes.py --apply

docker compose exec etl-worker python rebuild_geography.py
docker compose exec etl-worker python rebuild_geography.py --apply
```

Both are idempotent and safe to re-run — `provision_*` skips hosts already in
`dim_node`, and `rebuild_geography` rebuilds the dimensions from scratch each
time.

**Where the geography comes from.** NetXMS records a postal address per node,
so localities are read from the data rather than guessed from a name prefix.
`rebuild_geography.py` resolves each node through the real administrative
chain — `object_properties.siteadmin_id → siteadministratif → ville → commune →
province → limiteregion` — and falls back to matching the node's postal city
against a ville name. Regions are the **2025 découpage** (17 regions), labelled
with their former name (`Bankui (ex-Boucle du Mouhoun)`) because node addresses
still carry the pre-reform names. Localities get their coordinates from
`ST_Centroid(ville.geom)`; a locality with no coordinates does not appear on
the map.

Hosts whose location the inventory does not record land in a
`Siège / infrastructure centrale` fallback locality, shared by both
provisioning scripts so the dashboard never grows two different "unknown"
buckets.

> This reference data lives in the NetXMS database (`donnebase` schema), not
> behind its REST API — which is why `rebuild_geography.py` is the one piece of
> the ETL that reads a supervision tool's database directly (`NETXMS_DB_*` in
> `docker-compose.yml`). Collectors still go through the API.

---

## Incident lifecycle

Supervision tools report **current state**, not events: an alert that clears
simply stops being listed, and nothing ever announces that it ended. So each
collection pass is a reconciliation, not an append —
`/api/incidents/ingest/bulk` compares the batch against what is open and:

| In the batch | Already open in the DB | Result |
|---|---|---|
| ✅ | ❌ | **created** |
| ✅ | ✅ | ignored (idempotent — the same alert re-reported) |
| ❌ | ✅ | **resolved** — the alert cleared |

Deduplication and reconciliation both key on `(source_tool, external_id)`, so a
still-open problem re-reported every 5 minutes writes nothing.

**Empty batches never reconcile.** An empty active set is indistinguishable
from a collector that authenticated and returned nothing, so the backend skips
reconciliation for it and preserves every open incident's original
`detected_at` — and the MTTR figures derived from it. A genuine all-clear is
picked up by the next pass carrying at least one alert.

### Availability

`mv_kpi_node_monthly.availability_pct` measures **how long the node was
actually down**, which is not the same as the incidents raised:

- **Outages that are still open count.** Downtime is measured to `NOW()` while
  an incident is unresolved. (The obvious implementation — summing
  `downtime_minutes`, which is only written on resolution — reports 100%
  availability next to a thousand open incidents.)
- **An outage counts against every month it spans**, clipped to that month, not
  only the month it was detected in.
- **Overlapping incidents on one node count once.** `RANGE_AGG` unions the
  intervals; summing them would let a node with 27 concurrent alarms report
  negative availability.
- **The denominator is the elapsed part of the month**, so the current month is
  not diluted by days that have not happened yet.

`total_incidents` / `resolved` / `avg_mttr` keep their plain meaning —
incidents *detected* in that month. A node-month can therefore show 0 incidents
and still show degraded availability: an outage that started earlier and has
not cleared.

> Requires PostgreSQL 14+ for multirange support. `database/01_schema.sql` only
> runs on a fresh volume — an **existing** database needs the view dropped and
> recreated by hand to pick up a change to it.

The exact arithmetic behind every figure is in
[KPI calculations](#kpi-calculations) below.

---

## KPI calculations

Every number on the dashboard is derived, not stored. This section is the
reference for **how each one is computed** — the definitions the figures on
screen actually implement, so a value that looks surprising can be checked
rather than guessed at.

The chain is three layers deep, and each one is worth knowing because a KPI
that looks wrong is usually a layer question:

```
fact_incident              raw facts: one row per incident
        │                  (mttr_minutes, downtime_minutes, shift computed by Postgres)
        ▼
mv_kpi_node_monthly        one row per (node, month) — downtime unions + availability
        │                  (materialized: refreshed nightly at 02:00, or on every write)
        ▼
/api/kpi/*, /api/sla       network-wide aggregates + deltas
        │                  (Redis-cached for CACHE_TTL, flushed on any incident write)
        ▼
the dashboard
```

> **A stale figure is almost always a stale layer, not a wrong formula.** There
> are two:
>
> - **The materialized view.** With `SYNC_MV_REFRESH=true` (the default) every
>   ingest, acknowledge and resolve refreshes it synchronously; with `false` —
>   the production setting — the numbers only move at the nightly
>   `etl.refresh_kpi_view` job (02:00).
> - **The Redis cache**, `CACHE_TTL` seconds (default 300) per
>   `month`/`year`/params key. Writes through `/api/incidents/*` invalidate the
>   whole `kpi:` prefix, so ingestion is not affected by it — but a KPI that
>   changed *because time passed* is not a write and will sit until the TTL
>   lapses.
>
> That second case is specific to availability, which **drifts on its own**: an
> incident left open accrues downtime every minute without anything being
> written. It is only ever as current as the older of the two layers.
> `/api/interop/status` is deliberately excluded from the cache for the same
> reason — see [Collector status](#collector-status).

### 1. Base measures — computed by PostgreSQL on `fact_incident`

Two of the three are `GENERATED ALWAYS AS … STORED` columns, so they cannot
drift from their definition or be written inconsistently by a collector:

| Column | Formula | Notes |
|---|---|---|
| `mttr_minutes` | `EXTRACT(EPOCH FROM (resolved_at − detected_at)) / 60` | **`NULL` while the incident is open** — this is what makes every MTTR average below a resolved-incidents-only mean |
| `shift` | `'noc'` when `HOUR(detected_at)` ∈ [6, 21], else `'auto'` | Used only by `off_hours_detected` |
| `downtime_minutes` | Written on resolution: `max(⌊(resolved_at − detected_at) / 60⌋, 0)` | Not generated — a plain column defaulting to `0`, so it is **`0`, not `NULL`, while an incident is open** |

The `shift` column also declares a `'terrain'` branch (hours 7–16) that can
never be reached, since 7–16 is contained in 6–21 and the `CASE` matches the
first arm. Only `'noc'` and `'auto'` ever occur — `off_hours_detected` counts
`'auto'`, i.e. **incidents detected between 22:00 and 05:59**.

### 2. Per node-month — `mv_kpi_node_monthly`

For each `(node, month)`, incidents are attributed by `DATE_TRUNC('month', detected_at)`:

| Field | Formula |
|---|---|
| `total_incidents` | `COUNT(i.id)` — incidents **detected** in that month |
| `resolved` | `COUNT(*) FILTER (WHERE status IN ('resolved','closed'))` |
| `avg_mttr` | `AVG(mttr_minutes)` — SQL `AVG` skips `NULL`, so this is the mean over **resolved incidents only** |
| `total_downtime` | Minutes covered by the union of outage intervals, clipped to the month |
| `availability_pct` | `GREATEST(0, 100 − total_downtime / elapsed_minutes × 100)` |

**The outage interval** of an incident is `[detected_at, end)` where

```
end = NOW()                    if status ∈ ('open', 'acknowledged')
    = resolved_at              otherwise      (floored at detected_at, so never negative)
```

**Downtime** is a union, not a sum:

```
total_downtime(node, month) = minutes( ⋃ outage_i  ∩  [month_start, month_end) )
```

`RANGE_AGG` performs the union, which is what makes three properties hold at
once — a node with 27 concurrent alarms is down *once*, an outage spanning
March and April counts against **both** months clipped to each, and an outage
still open right now counts to `NOW()` instead of contributing nothing.

**The denominator is the elapsed part of the month**, never the whole month:

```
elapsed_minutes = ( LEAST(month_start + 1 month, NOW()) − month_start ) / 60 s
availability_pct = max(0, 100 − total_downtime / max(elapsed_minutes, 1) × 100)
```

So the current month is judged on the days that have actually happened. The
`GREATEST(0, …)` floor and the `max(…, 1)` guard are there for a future month
(elapsed ≤ 0) and for pathological data — a clock-skewed `detected_at` in the
future, say — which would otherwise produce a negative percentage.

### 3. Network-wide — the KPI cards (`GET /api/kpi/summary`)

Aggregated over every row of the view for the month:

| Field (card label where shown) | Formula |
|---|---|
| `total_incidents` — **Total Incidents** | `SUM(total_incidents)` |
| `resolved` | `SUM(resolved)` |
| `open` | `SUM(total_incidents) − SUM(resolved)` |
| `resolution_rate_pct` — **Taux de Résolution** | `resolved / total × 100`, 1 decimal — **`0.0` when the month has no incidents**, not 100 |
| `avg_mttr_minutes` — **MTTR Moyen** | `AVG(mv.avg_mttr)` — the mean **of the per-node means** |
| `network_availability_pct` — **Disponibilité Réseau** | `AVG(mv.availability_pct)` — the mean **per node-month**, defaulting to `100` when the month has no rows at all |
| `critical_localities` | `COUNT(DISTINCT locality_id)` where `availability_pct < 95` |
| `recurrent_nodes` | `COUNT(*)` node-months with `total_incidents ≥ 3` |
| `off_hours_detected` | `COUNT(*)` incidents in the month with `shift = 'auto'` |

Two of these are **unweighted means of means**, which is a deliberate choice
worth being explicit about:

- **MTTR moyen** averages each node's own average, so a node with one 10-hour
  incident weighs exactly as much as a node with 200 five-minute ones. It
  answers "how long does a typical *node* take to recover", not "how long does
  a typical *incident* last". The incident-weighted figure would be
  `SUM(mttr × n) / SUM(n)`, and it is not what this endpoint returns.
- **Disponibilité réseau** averages per node-month, so every node counts once
  regardless of size — a core router and a small access node move the number
  equally. Weighting by capacity or by served population would need a weight
  column that `dim_node` does not carry.

> ⚠️ **Availability is measured over affected nodes only.** A node only enters
> `mv_kpi_node_monthly` for a month if it has an incident overlapping it, so a
> node that was never down all month is **not** in the average as a 100%. The
> published figure is therefore the mean availability *of the nodes that had at
> least one incident*, which is pessimistic — and it moves for a reason that is
> easy to misread: a quiet month with few affected nodes can score *lower* than
> a busy one, because a single badly-hit node is a larger share of a smaller
> denominator.

**Deltas.** `vs_previous_month` compares the same month-1: `incidents_delta` is
a plain difference in count, `availability_delta` a difference in **percentage
points** (not a percentage change). `GET /api/kpi/compare` does the same
against N-1 and N-3 months across the five headline KPIs.

### 4. SLA indicators (`GET /api/sla`)

Three indicators, each compared to a fixed target from `SLA_TARGETS`
(`backend/app/services/kpi_service.py`). Status is simply `value ≥ target →
met`, otherwise `not_met` — there is no tolerance band:

| Indicator | Target | Computed as |
|---|---|---|
| **Disponibilité Cœur de Réseau** | ≥ 99.5 % | `AVG(availability_pct)` restricted to node-months whose `source_tool` is `centreon` or `netxms` |
| **Disponibilité Nœuds d'Accès** | ≥ 95 % | The network availability above, unrestricted |
| **Taux de Résolution < 4h** | ≥ 80 % | The resolution rate above |

"Core network" is thus **defined by which tool supervises a node**, not by a
node-type or capacity attribute: Centreon and NetXMS monitor the backbone here,
Zabbix/Nagios the access layer. Re-point a tool and this indicator's population
changes with it. If no node-month matches (neither tool configured, or no
incidents from them), it falls back to the overall network availability rather
than reporting an empty indicator.

> ⚠️ **The "< 4h" in the third label is not implemented.** The value plotted
> against it is the plain resolution rate — *resolved ÷ detected* — with no
> filter on `mttr_minutes < 240`. The indicator is therefore optimistic against
> its own stated target: an incident resolved after three days counts exactly
> like one resolved in ten minutes. Making the label true means counting
> `COUNT(*) FILTER (WHERE mttr_minutes < 240) / COUNT(*)`; leaving the code as
> it is means the label should read "Taux de résolution".

### 5. Recurrent and flapping nodes (`GET /api/kpi/recurrent`)

A node-month qualifies as recurrent at `total_incidents ≥ min_count` (default
3). Each one then gets a **mean episode length**, which is what separates the
two shapes that a bare incident count cannot:

```
avg_duration_minutes = AVG( COALESCE(downtime_minutes, (NOW() − detected_at)/60) )
flapping             = avg_duration_minutes < 15 minutes
```

15 minutes sits well above a 5-minute poll interval (so a genuinely short
outage is not mislabelled) and well below any outage worth dispatching a team
for. A **flapping** node produces many short episodes — fix the link; a
**chronic** one produces few long ones — send someone to the site.

> ⚠️ Because `downtime_minutes` defaults to `0` rather than `NULL` (§1), the
> `COALESCE` never falls through for a currently-open incident: an ongoing
> outage contributes **0 minutes** to this average instead of its running
> duration. A node whose incidents are mostly still open is therefore reported
> as *flapping* when it may be the opposite. Availability is unaffected — the
> view measures open outages to `NOW()` independently of this column.

### 6. The remaining views

| Endpoint | Computation |
|---|---|
| `GET /api/kpi/trend` | The same summary aggregate, re-run for each of the last N months (default 6) |
| `GET /api/kpi/hour-distribution` | `COUNT(*)` grouped by `EXTRACT(HOUR FROM detected_at)`, zero-filled to all 24 hours |
| `GET /api/kpi/causes` | `COUNT(*)` and `AVG(mttr_minutes)` per `dim_cause.category`, **outer**-joined so incidents with no cause fall into `Non classé` instead of vanishing — the breakdown sums to the month's real total, and the size of that slice is the honest measure of how much classification is still missing |
| `GET /api/kpi/localities` | The view's fields summed/averaged per locality, ranked by incident count |
| `GET /api/kpi/localities/map` | Same, but starting from `dim_locality` so localities with **zero** incidents still appear (availability defaults to 100), plus per-severity counts for the Carte filters |

Cause classification happens in the ETL, not in SQL: `etl/transform/causes.py`
matches the alert text against a taxonomy of what the tools actually observe
("Nœud injoignable (ICMP)", "Interface hors service"). Text nothing matches
stays uncategorised rather than being forced into an "Autre" bucket that would
quietly become the largest cause on the dashboard.

---

## Collector status

The **Interopérabilité** tab reports what each collector is actually doing, rather than asserting that the integrations work. `GET /api/interop/status` combines two things the dashboard cannot get from one place: the ETL worker's last collection pass, and the incidents raised this month **grouped by the tool that reported them** (`fact_incident.source_tool` — not `dim_node.source_tool`, which records the tool nominally responsible for a node and legitimately disagrees).

Each of the five tools reports one of:

| State | Meaning |
|---|---|
| `ok` | The tool answered and everything fetched was ingested |
| `degraded` | The tool answered, but some incidents failed to reach the backend |
| `error` | The collector could not complete — the supervision API's own error is carried in `detail` |
| `not_configured` | No `*_API_URL` is set, so the collector never ran |
| `unknown` | No status published within the key's lifetime — the worker is stopped or unreachable |

Only `ok` is shown in green. The status key expires after three poll intervals, so a worker that dies leaves the page reporting `unknown` rather than continuing to display its last successful pass as though it were current — a stale green badge is worse than no badge, because it is believed. For the same reason the endpoint is **not cached**: serving liveness from a five-minute cache reintroduces exactly the lag that makes a status display untrustworthy.

This is also the quickest way to diagnose a tool that has stopped producing incidents — expired credentials surface here as `error` with the API's own message, instead of only in `docker compose logs etl-worker`.

---

## Further Documentation

This README covers setup and a high-level tour. For deeper technical
reference, see [`docs/`](docs/):

| Document | Covers |
|---|---|
| [docs/architecture.md](docs/architecture.md) | System diagram, request/data flow, caching strategy, design system internals |
| [docs/api-reference.md](docs/api-reference.md) | Every endpoint: auth, params, request/response shapes, error codes |
| [docs/database-schema.md](docs/database-schema.md) | Tables, columns, relationships, the `mv_kpi_node_monthly` materialized view, indexes |
| [docs/deployment.md](docs/deployment.md) | Services, env vars, `deployment.sh`, TLS, backups, production hardening checklist |
| [docs/integrations.md](docs/integrations.md) | Zabbix/Nagios/Centreon/NetXMS/iTop collector contracts and Web Push/VAPID setup |

Two more references live outside `docs/`:

| Document | Covers |
|---|---|
| [SERVER_DATA.md](SERVER_DATA.md) | Every API call, run against the bundled instances: which field of which tool's payload feeds which column of the star schema, and the transformation in between |
| `backend/docker-images/*/README.md` | The Centreon and NetXMS images built here — what upstream doesn't publish, and how each container is wired |

---

## Contributing

1. **Fork** the repository and create a feature branch:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** and ensure code quality:
   ```bash
   # Frontend linting
   cd frontend && npm run lint

   # Backend: run the test suite (68 tests — auth, RBAC, rate limiting, ingest
   # reconciliation, KPI math, notifications, reports)
   cd backend
   pip install -r requirements-dev.txt
   pytest
   ```

3. **Commit** with a clear message:
   ```bash
   git commit -m "feat: add your feature description"
   ```

4. **Push** and open a Pull Request.

---

<div align="center">
  <sub>Built for <strong>ANPTIC</strong> — Agence Nationale de Promotion des TIC</sub>
</div>
