# Integrations

How the dashboard connects to external supervision/ITSM tools. The ETL runs
**real collectors**: each supervision tool is polled through its actual API as
soon as its endpoint is configured — no simulation. A collector is enabled iff
its `*_API_URL` environment variable is set; leave it empty to disable that
tool. To integrate a tool, set its URL + credentials in `.env` and restart
`etl-worker`.

**Local server instances** — `docker-compose.yml` now ships Zabbix 7.0 LTS
(server + web + agent + its own PostgreSQL), Nagios Core and iTop (embedded
MariaDB) alongside the dashboard, pre-wired to the collectors via `.env`:

| Tool | UI (host) | In-network endpoint the ETL/backend uses | Default login |
|---|---|---|---|
| Zabbix | http://localhost:8081 | `http://zabbix-web:8080/api_jsonrpc.php` | `Admin` / `zabbix` |
| Nagios | http://localhost:8083 | `http://nagios/cgi-bin/statusjson.cgi` | `$NAGIOS_USER` / `$NAGIOS_PASSWORD` |
| iTop | http://localhost:8082 | `http://itop/webservices/rest.php` | created in setup wizard |

iTop requires a **one-time setup wizard** on first start (DB server
`localhost`, login `admin`, password `$ITOP_DB_PASSWORD`). Centreon and NetXMS
have no vendor-supported Docker images — their collectors stay disabled until
you point their `*_API_URL` at an external server (Centreon can also push
webhooks, see below).

For incidents to flow from Zabbix/Nagios into the dashboard, the hosts you
create in those tools must match a `dim_node` (see
[Host → node matching](#host--node-matching)) — name a Zabbix/Nagios host
after a node code (e.g. `DED-001`) or node name, and set `dim_node.source_tool`
accordingly.

## Table of Contents

- [Summary](#summary)
- [How collection works](#how-collection-works)
- [Per-tool configuration](#per-tool-configuration)
- [Host → node matching](#host--node-matching)
- [Deduplication](#deduplication)
- [Centreon webhooks (push)](#centreon-webhooks-push)
- [iTop (ITSM / CMDB)](#itop-itsm--cmdb)
- [Web Push (browser/PWA)](#web-push-browserpwa)
- [Webhook authentication](#webhook-authentication)

---

## Summary

| System | Protocol | Status | Config vars |
|---|---|---|---|
| **Zabbix** | JSON-RPC `event.get` (§6.1) | **Implemented** (`etl/extract/zabbix.py`) | `ZABBIX_API_URL`, `ZABBIX_USER`/`ZABBIX_PASSWORD` or `ZABBIX_API_TOKEN` |
| **Nagios** | `statusjson.cgi?query=hostlist` (§6.2) | **Implemented** (`etl/extract/nagios.py`) | `NAGIOS_API_URL`, `NAGIOS_USER`/`NAGIOS_PASSWORD` and/or `NAGIOS_API_KEY` |
| **NetXMS** | REST `/alarms` (web API daemon) | **Implemented** (`etl/extract/netxms.py`) | `NETXMS_API_URL`, `NETXMS_USER`, `NETXMS_PASSWORD` |
| **Centreon** | REST v2 `/monitoring/resources` (§6.3) + inbound webhook | **Implemented** (`etl/extract/centreon.py`) | `CENTREON_API_URL`, `CENTREON_USER`/`CENTREON_PASSWORD` or `CENTREON_API_KEY` |
| **iTop** | REST webservice (`core/create` on class `Incident`) | **Implemented** (`backend/app/services/itop_service.py`) | `ITOP_URL`, `ITOP_USER`, `ITOP_PASS`, `ITOP_ORG_ID` |
| **Twilio (SMS)** | REST API (`Messages.json`) | **Implemented** (`backend/app/services/notification_service.py`) | `NOTIFICATIONS_ENABLED`, `TWILIO_*`, `NOC_SMS_RECIPIENTS` |
| **SMTP (email)** | SMTP + STARTTLS | **Implemented** (same service) | `SMTP_*`, `NOC_EMAIL_RECIPIENTS` |
| **Web Push (browser/PWA)** | Web Push protocol, VAPID-signed | **Implemented** (`backend/app/services/push_service.py`) | `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_CLAIMS_EMAIL` |

## How collection works

`etl-beat` schedules `etl.collect_supervision` every `ETL_COLLECT_INTERVAL_S`
seconds (default **300** — the spec's §2.2 five-minute batch). Each pass:

1. Loads all active nodes (code, name, IP, source_tool) from Postgres.
2. For each **configured** tool, calls its `fetch_events(nodes, since)`
   collector. `since` is the tool's last successful poll, tracked in Redis
   (`etl:last_poll:{tool}`) so a worker restart doesn't re-fetch history
   (first run looks back two intervals).
3. Normalizes each event (`transform/normalize.py`) and POSTs it to
   `POST /api/incidents/ingest` with the static `NOC_API_KEY`.
4. Failures are **isolated per tool** — an unreachable Zabbix never blocks
   Nagios collection. Each pass logs `[tool] fetched=N ingested=M` and returns
   a per-tool stats dict (visible in `docker compose logs etl-worker`).

If **no** tool is configured, the task logs "nothing to collect" and exits —
the dashboard then only shows seeded/historical data and whatever arrives by
webhook.

## Per-tool configuration

**Zabbix** — set `ZABBIX_API_URL` to the JSON-RPC endpoint
(e.g. `https://zabbix.anptic.bf/api_jsonrpc.php`). Auth: either
`ZABBIX_API_TOKEN` (Zabbix ≥ 5.4, preferred) or `ZABBIX_USER`/`ZABBIX_PASSWORD`
(`user.login` is called on every poll — its token is only valid ~30 min, so it
is not cached). Fetches trigger PROBLEM events (`event.get`, `value=1`) since
the last poll, with `selectHosts` for node matching. Severity map: Zabbix 0–5 →
`low, low, medium, medium, high, critical`.

**Nagios** — set `NAGIOS_API_URL` to the base URL that fronts the CGIs
(e.g. `https://nagios.anptic.bf/nagios`; the collector appends
`/cgi-bin/statusjson.cgi`). Auth: Basic (`NAGIOS_USER`/`NAGIOS_PASSWORD`)
and/or `NAGIOS_API_KEY` sent as `X-Auth-Token` (spec §6.2). Polls **current
host status**: state `4` (DOWN) → `critical`, `8` (UNREACHABLE) → `high`.
Because status (not an event log) is polled, a host that stays down is
re-reported each pass with the stable id `nagios-{host}-down` — deduplicated
by the backend.

**NetXMS** — set `NETXMS_API_URL` to the web API daemon base
(e.g. `https://netxms.anptic.bf/rest`; the collector calls `/alarms` with
Basic auth). Active alarms map severity 0–4 (NORMAL…CRITICAL) →
`low, medium, medium, high, critical`; NORMAL alarms are ignored. Alarm ids
are stable → deduplicated while active.

**Centreon** — set `CENTREON_API_URL` to the v2 API base
(e.g. `https://centreon.anptic.bf/centreon/api/latest`). Auth: static
`CENTREON_API_KEY` (sent as `X-AUTH-TOKEN`) or `CENTREON_USER`/`CENTREON_PASSWORD`
(a `/login` call per poll). Fetches unhandled `CRITICAL`/`UNKNOWN`/`DOWN`
resources (§6.3's `status IN (2,3)` filter). For service resources the
**parent host** name is used for node matching.

## Host → node matching

Collectors map each tool's host reference onto a `dim_node` **code** (what
`/ingest` requires), trying in order (`etl/extract/common.py`):

1. exact node `code` (e.g. the Zabbix host is literally named `DED-001`),
2. exact node `name` (case-insensitive, e.g. `DREP Dédougou`),
3. exact `ip_address`.

Unmatched hosts are logged as a warning and skipped — align the supervision
tool's host names with the CMDB (or fill in `dim_node.ip_address`) to make
them flow. Each tool only sees the nodes whose `dim_node.source_tool` matches
it, so the same host name in two tools can't cross-match.

## Deduplication

`POST /api/incidents/ingest` is **idempotent** on
`(source_tool, external_id)`: if an incident with the same pair is still
`open`/`acknowledged`, the backend returns it (HTTP `200`, no new row, no
WebSocket broadcast, no SMS/email) instead of creating a duplicate — required
because status-based pollers (Nagios, NetXMS, Centreon) legitimately re-report
active problems every pass. A `resolved`/`closed` incident does **not** match:
the same alert firing again after recovery is a new incident.

## Centreon webhooks (push)

Independently of the 5-minute batch, Centreon (or any tool) can push alerts in
real time by POSTing directly to `/api/incidents/ingest` with
`Authorization: Bearer $NOC_API_KEY` — see the payload contract in
[api-reference.md](api-reference.md#post-apiincidentsingest) and the broker
configuration example in the cahier des charges §6.3. Webhook-pushed and
batch-collected alerts coexist safely thanks to the deduplication above.

## iTop (ITSM / CMDB)

`backend/app/services/itop_service.py` makes a real REST call —
`core/create` on class `Incident` — whenever an ingest payload sets
`itop_auto_ticket: true` (the ETL sets this for `critical`/`high` events in
`transform/normalize.py`). It maps the incident's `severity` onto iTop's
`urgency` enum (`critical→1`, `high→2`, `medium→3`, `low→4`) and returns the
created ticket's reference (e.g. `I-000042`), stored in
`fact_incident.itop_ticket_id`. Like the SMS/email notifier, it **degrades
gracefully**: any failure (iTop unreachable, rejected fields, timeout) is
logged and the call returns `null` rather than blocking incident ingestion.

**One-time setup required before this works:**

1. **Run the setup wizard** — first visit to `http://localhost:8082` (the
   bundled iTop container) redirects there. Use DB server `localhost`, login
   `admin`, password `$ITOP_DB_PASSWORD`; create an admin account matching
   `ITOP_USER`/`ITOP_PASS` in `.env`. (Pointing `ITOP_URL` at an external iTop
   instance instead just needs an existing admin account there.)
2. **Grant the `REST Services User` profile** to that account. iTop separates
   "can use the web UI" (the `Administrator` profile, granted by the wizard)
   from "can call the REST webservice" — without this second profile,
   `core/create` returns `Error: This user is not authorized to use the web
   services.` even with correct credentials. In the iTop UI: *Administration →
   Users*, open the account, add the `REST Services User` profile.
3. Set `ITOP_ORG_ID` in `.env` to the `id` of the Organization tickets should
   be created under (a fresh install has exactly one: `1`, "My
   Company/Department"). `org_id` is a mandatory field on `Incident` — ticket
   creation fails without it.

`dim_node.itop_ci_id` exists in the schema for linking a node to its iTop CMDB
CI record, but nothing currently populates or reads it outside seed data.

## Web Push (browser/PWA)

`backend/app/services/push_service.py` sends real Web Push notifications
(VAPID-signed, RFC 8291/8292) to every subscribed browser/PWA when a
**critical** incident is ingested — alongside, not instead of, the SMS/email
notifications.

**Generating a VAPID keypair** — the format `pywebpush`/`py_vapid` expect is a
raw, base64url-encoded EC (P-256) key pair, not PEM:

```bash
docker compose exec backend python3 -c "
from py_vapid import Vapid
import base64
from cryptography.hazmat.primitives import serialization

v = Vapid()
v.generate_keys()

priv_val = v.private_key.private_numbers().private_value
private_b64url = base64.urlsafe_b64encode(priv_val.to_bytes(32, 'big')).decode().rstrip('=')

raw_pub = v.public_key.public_bytes(
    encoding=serialization.Encoding.X962,
    format=serialization.PublicFormat.UncompressedPoint,
)
public_b64url = base64.urlsafe_b64encode(raw_pub).decode().rstrip('=')

print('VAPID_PUBLIC_KEY=' + public_b64url)
print('VAPID_PRIVATE_KEY=' + private_b64url)
"
```

Paste the output into `.env` (`VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`) and set
`VAPID_CLAIMS_EMAIL` to a contact address (sent as the push protocol's `sub`
claim). **Generate a fresh keypair per environment** — the one shipped in this
repo's `.env` is for local/demo use only; a production deployment reusing it
would let anyone with the repo forge push messages to real subscribers.

**Flow**: the frontend's bell toggle (`Header.jsx` /
`usePushNotifications.js`) requests `Notification` permission, subscribes via
`PushManager.subscribe()` using `VAPID_PUBLIC_KEY` (fetched from
`GET /api/notifications/vapid-public-key`) as the `applicationServerKey`, then
registers the subscription (`endpoint` + `p256dh`/`auth` keys) with
`POST /api/notifications/subscribe`, stored in the `push_subscription` table
(one row per user per device/browser — see
[database-schema.md](database-schema.md)). On a critical incident,
`push_service.notify_critical_incident_push` sends to every stored
subscription; a `404`/`410` response (the browser dropped the subscription —
uninstalled, permission revoked) prunes that row automatically.

## Webhook authentication

All external systems calling into this API authenticate with a single static
bearer key, not per-tool credentials:

```
Authorization: Bearer $NOC_API_KEY
```

checked by `verify_api_key` (`backend/app/core/security.py`) on
`POST /api/incidents/ingest` (and accepted on `GET /api/report/monthly` for
the scheduled export). This matches cahier des charges §10.1 ("clé API
statique pour les webhooks"). The per-tool `ZABBIX_*`/`NAGIOS_*`/`NETXMS_*`/
`CENTREON_*` variables are for the **outbound** direction — what the ETL uses
to poll those tools' own APIs — separate from the shared inbound `NOC_API_KEY`
tools use to push webhooks to `/ingest`.
