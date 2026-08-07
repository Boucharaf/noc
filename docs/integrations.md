# Integrations

How the dashboard connects to external supervision/ITSM tools. The ETL runs
**real collectors**: each supervision tool is polled through its actual API as
soon as its endpoint is configured — no simulation. A collector is enabled iff
its `*_API_URL` environment variable is set; leave it empty to disable that
tool. To integrate a tool, set its URL + credentials in `.env` and restart
`etl-worker`.

**Local server instances** — `docker-compose.yml` now ships Zabbix 7.0 LTS
(server + web + agent + its own PostgreSQL), Nagios Core, NetXMS (server +
Web API + its own PostgreSQL), Centreon 24.10 (central + its own MariaDB) and
iTop (embedded MariaDB) alongside the dashboard, pre-wired to the collectors
via `.env`:

| Tool | UI (host) | In-network endpoint the ETL/backend uses | Default login |
|---|---|---|---|
| Zabbix | http://localhost:8081 | `http://zabbix-web:8080/api_jsonrpc.php` | `Admin` / `zabbix` |
| Nagios | http://localhost:8083 | `http://nagios/cgi-bin/statusjson.cgi` | `$NAGIOS_USER` / `$NAGIOS_PASSWORD` |
| NetXMS | http://localhost:8086 (nxmc web console) | `http://netxms:8000` (REST v1) | `admin` / `$NETXMS_PASSWORD` |
| Centreon | http://localhost:8084/centreon | `http://centreon/centreon/api/latest` (REST v2) | `admin` / `$CENTREON_PASSWORD` |
| iTop | http://localhost:8082 | — (standalone ITSM/CMDB tool, no backend integration) | created in setup wizard |

iTop requires a **one-time setup wizard** on first start (DB server
`localhost`, login `admin`, password `$ITOP_DB_PASSWORD`); it ships purely as
a standalone tool in the stack. NetXMS publishes no official Docker image, so
its image is built from `backend/docker-images/netxms` (see the README there);
`$NETXMS_PASSWORD` is applied to the built-in `admin` account the first time
the schema is created, and the Web API is also exposed on
http://localhost:8085. Its console is a separate component, built from
`backend/docker-images/netxms-webui` (Tomcat + `nxmc.war`) and served on
http://localhost:8086 — it reaches the server over NXCP on port 4701, which is
a binary protocol, not HTTP. Centreon has no vendor-supported Docker image
either, so its image is built from `backend/docker-images/centreon`: the
container installs a full central (web + REST API v2 + engine + broker +
gorgone) against the `centreon-db` MariaDB and runs Centreon's install wizard
**unattended** on first start, which takes a few minutes — it only reports
healthy once the API answers a login. `$CENTREON_PASSWORD` becomes the `admin`
password and must satisfy Centreon's policy (12+ characters, a lower case, an
upper case, a digit and one of `@$!%*?&`, nothing else). Centreon can also push
webhooks instead of, or alongside, being polled (see below).

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
- [Web Push (browser/PWA)](#web-push-browserpwa)
- [Webhook authentication](#webhook-authentication)

---

## Summary

| System | Protocol | Status | Config vars |
|---|---|---|---|
| **Zabbix** | JSON-RPC `problem.get` (§6.1) | **Implemented** (`etl/extract/zabbix.py`) | `ZABBIX_API_URL`, `ZABBIX_USER`/`ZABBIX_PASSWORD` or `ZABBIX_API_TOKEN` |
| **Nagios** | `statusjson.cgi?query=hostlist` (§6.2) | **Implemented** (`etl/extract/nagios.py`) | `NAGIOS_API_URL`, `NAGIOS_USER`/`NAGIOS_PASSWORD` and/or `NAGIOS_API_KEY` |
| **NetXMS** | REST API v1: `POST /v1/login` → bearer token, then `/v1/alarms` + `/v1/objects` | **Implemented** (`etl/extract/netxms.py`) | `NETXMS_API_URL`, `NETXMS_USER`, `NETXMS_PASSWORD` |
| **Centreon** | REST v2 `/monitoring/resources` (§6.3) + inbound webhook | **Implemented** (`etl/extract/centreon.py`) | `CENTREON_API_URL`, `CENTREON_USER`/`CENTREON_PASSWORD` or `CENTREON_API_KEY` |
| **Twilio (SMS)** | REST API (`Messages.json`) | **Implemented** (`backend/app/services/notification_service.py`) | `NOTIFICATIONS_ENABLED`, `TWILIO_*`, `NOC_SMS_RECIPIENTS` |
| **SMTP (email)** | SMTP + STARTTLS | **Implemented** (same service) | `SMTP_*`, `NOC_EMAIL_RECIPIENTS` |
| **Web Push (browser/PWA)** | Web Push protocol, VAPID-signed | **Implemented** (`backend/app/services/push_service.py`) | `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_CLAIMS_EMAIL` |

## How collection works

`etl-beat` schedules `etl.collect_supervision` every `ETL_COLLECT_INTERVAL_S`
seconds (default **300** — the spec's §2.2 five-minute batch). Each pass:

1. Loads all active nodes (code, name, IP, source_tool) from Postgres.
2. For each **configured** tool, calls its `fetch_events(nodes)` collector,
   which returns the problems that tool reports as open at that moment. No
   cursor is kept: every pass sees current state, so a missed pass, a failed
   ingest or a worker restart costs nothing — the next pass reports the same
   problems and the backend deduplicates them.
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
is not cached). Polls the **currently unresolved** trigger problems
(`problem.get`), not the event stream since the last poll: §6.1 names
`event.get`, but that offered each event in exactly one poll window, so a
problem raised before the collector first ran — or during any gap longer than
the look-back — could never reach the dashboard. Problems that stay open are
re-reported each pass under their stable event id and deduplicated by the
backend, as with the other current-state collectors. `problem.get` rejects
`selectHosts`, so the hosts come from a follow-up `trigger.get` on the
problem's `objectid`; problems `suppressed` by a maintenance window are
dropped. Severity map: Zabbix 0–5 → `low, low, medium, medium, high, critical`.

**Nagios** — set `NAGIOS_API_URL` to the base URL that fronts the CGIs
(e.g. `https://nagios.anptic.bf/nagios`; the collector appends
`/cgi-bin/statusjson.cgi`). Auth: Basic (`NAGIOS_USER`/`NAGIOS_PASSWORD`)
and/or `NAGIOS_API_KEY` sent as `X-Auth-Token` (spec §6.2). Polls **current
host status** with `details=true`: state `4` (DOWN) → `critical`, `8`
(UNREACHABLE) → `high`. Because status (not an event log) is polled, a host
that stays down is re-reported each pass with the stable id
`nagios-{host}-down` — deduplicated by the backend. `details=true` also
supplies `last_state_change`, which dates the outage from when Nagios saw it
rather than from when we polled (otherwise a host already down when collection
starts loses all its earlier downtime from the KPIs), and `plugin_output` for
the description. Older servers that ignore `details` return the bare status
code and fall back to the poll time and a generic label. Nagios exposes no
host address here, so matching is **by name only** — name hosts after their
node code.

**NetXMS** — set `NETXMS_API_URL` to the REST API v1 base (`http://netxms:8000`
for the container in this stack, or e.g. `http://netxms.anptic.bf:8000` for an
external server; no trailing `/v1`). Auth is token-based,
not Basic: the collector `POST`s `{"username": NETXMS_USER, "password":
NETXMS_PASSWORD}` to `/v1/login`, gets back a bearer token (short-lived, so it
logs in on every poll — same approach as Zabbix/Centreon), then calls
`/v1/alarms` (a flat list of `{id, severity, state, source, message,
lastChangeTime}`) and `/v1/objects` with `Authorization: Bearer <token>`.
An alarm's numeric `source` id is resolved to an object name and primary IP for
node matching. `/v1/objects` supplies those in one call, but it does not
enumerate every Node — on the server in this stack it returns only the seven
root containers — so an id missing from that listing is fetched individually
with `/v1/objects/{id}` (once per distinct source per poll, cached). An id that
resolves to neither falls back to the raw numeric id (normally unmatched,
logged, and skipped like any other unprovisioned host). Alarm `state` 2 (terminated/resolved) is dropped;
severity 0–4 (NORMAL…CRITICAL) maps to `low, medium, medium, high, critical`,
with NORMAL alarms also ignored. Alarm ids are stable → deduplicated while
active.

**Centreon** — set `CENTREON_API_URL` to the v2 API base
(`http://centreon/centreon/api/latest` for the container in this stack, or
e.g. `https://centreon.anptic.bf/centreon/api/latest` for an external server).
Auth: static `CENTREON_API_KEY` (sent as `X-AUTH-TOKEN`) or
`CENTREON_USER`/`CENTREON_PASSWORD` (a `/login` call per poll). Fetches
unhandled `CRITICAL`/`UNKNOWN`/`DOWN` resources (§6.3's `status IN (2,3)`
filter). For service resources the **parent host** name is used for node
matching.

The local container starts with a single host — the central monitoring itself
by ping — because a fresh Centreon has no host templates: those come from
plugin packs, imported from Centreon's repository under a licence. Hosts
created by hand with an explicit check command need none of that; see the
recipe in `backend/docker-images/centreon/README.md` for adding a host named
after a node code and watching it go DOWN into the dashboard.

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
