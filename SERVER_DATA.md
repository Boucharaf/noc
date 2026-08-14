# Supervision data → BI model

How to pull useful data out of the five tools in the stack (Zabbix, Nagios,
NetXMS, Centreon, iTop), and how each field has to be transformed to land
**exactly** in the dashboard's star schema.

Every call below was run against the local instances in `docker-compose.yml`.
Credentials are the `.env` variables, never literals — export them first:

```bash
set -a; source .env; set +a
```

- [1. The target: what the BI actually stores](#1-the-target-what-the-bi-actually-stores)
- [2. Which KPI depends on which field](#2-which-kpi-depends-on-which-field)
- [3. The three gaps every collector shares](#3-the-three-gaps-every-collector-shares)
- [4. Zabbix](#4-zabbix)
- [5. Nagios](#5-nagios)
- [6. NetXMS](#6-netxms)
- [7. Centreon](#7-centreon)
- [8. iTop](#8-itop)
- [9. Cross-tool field mapping](#9-cross-tool-field-mapping)
- [10. Filling dim_cause](#10-filling-dim_cause)

---

## 1. The target: what the BI actually stores

Nothing reaches the database directly. Every tool goes through one contract —
`POST /api/incidents/ingest`, `Authorization: Bearer $NOC_API_KEY`
(`backend/app/schemas/incidents.py`):

| Payload field | Required | Constraint | Lands in |
|---|---|---|---|
| `external_id` | ✔ | any string, **stable for the life of the problem** | `fact_incident.external_id` |
| `source_tool` | ✔ | `zabbix\|nagios\|netxms\|centreon\|itop` | `fact_incident.source_tool` |
| `node_code` | ✔ | must match an existing `dim_node.code` | resolved to `fact_incident.node_id` |
| `severity` | | `critical\|high\|medium\|low` (default `medium`) | `fact_incident.severity` |
| `status` | | `open\|acknowledged\|resolved\|closed` (default `open`) | `fact_incident.status` |
| `detected_at` | ✔ | ISO 8601, UTC | `fact_incident.detected_at` |
| `description` | | free text | `fact_incident.description` |
| `cause_category` + `cause_label` | | pair, created on the fly | `dim_cause` → `fact_incident.cause_id` |
| `itop_ticket_id` | | e.g. `I-023404` | `fact_incident.itop_ticket_id` |

Three columns are **not** in the payload and cannot be set at ingest:

| Column | How it gets a value |
|---|---|
| `acknowledged_at` | `PATCH /api/incidents/{id}/acknowledge` |
| `resolved_at` | `PATCH /api/incidents/{id}/resolve` |
| `downtime_minutes` | computed on resolve: `resolved_at - detected_at`, in minutes |
| `mttr_minutes` | generated column, `(resolved_at - detected_at)/60` |
| `shift` | generated column from `detected_at`'s hour (`noc` 06–21, else `auto`) |

**Idempotence.** `(source_tool, external_id)` is matched against incidents still
`open`/`acknowledged`; a re-report updates nothing and creates nothing. Once an
incident is `resolved`, the same `external_id` arriving again is treated as a
new incident — which is correct for a host that goes down, recovers, and goes
down again. This is why `external_id` must be stable **while the problem
lasts** and must not encode a timestamp.

---

## 2. Which KPI depends on which field

`mv_kpi_node_monthly` aggregates `fact_incident` per month per node, and every
dashboard figure comes from it (`backend/app/services/kpi_service.py`):

| Dashboard figure | Formula | Needs |
|---|---|---|
| Total incidents | `COUNT(*)` | `detected_at`, `node_id` |
| Resolved / Open | `COUNT(status='resolved')` | **`status`** |
| Resolution rate | `resolved / total` | **`status`** |
| Average MTTR | `AVG(mttr_minutes)` | **`resolved_at`** |
| Network availability | `100 - SUM(downtime_minutes)/(24*60*30)*100` | **`downtime_minutes`** |
| Critical localities | availability `< 95%` | **`downtime_minutes`** |
| Recurrent nodes | `total_incidents >= 3` | `node_id` |
| Off-hours detected | `shift = 'auto'` | `detected_at` (hour) |
| Cause breakdown | `GROUP BY dim_cause` | **`cause_category`/`cause_label`** |
| SLA — core availability | availability over `source_tool IN ('centreon','netxms')` | **`downtime_minutes`**, `source_tool` |
| Hourly distribution | `EXTRACT(HOUR FROM detected_at)` | `detected_at` |
| N / N-1 / N-3 comparison | same aggregates, shifted months | `detected_at` |

The bolded inputs are exactly the ones no collector supplies today.

Two quirks to know before reading a figure literally:

- `availability_pct` divides by a fixed **30-day** month, so a 31-day month is
  scored slightly harshly and February slightly kindly.
- the generated `shift` column has three branches but can only ever produce two:
  `noc` covers hours 6–21, and the `terrain` branch (7–16) is inside it, so it
  is unreachable. "Off-hours detected" (`shift = 'auto'`) is therefore
  everything outside 06:00–21:59, which is what the dashboard actually means —
  but nothing is ever attributed to `terrain`.

---

## 3. The three gaps every collector shares

`etl/extract/*.py` all produce the same shape and always leave the same fields
empty (`etl/transform/normalize.py` hardcodes `status="open"`):

**Gap 1 — nothing ever closes.** Every incident is ingested `open` and stays
open until a human resolves it in the dashboard. So MTTR, resolution rate,
availability, downtime and the SLA panel are driven by manual action, not by
the supervision tools — even though **all five tools publish the recovery**:

| Tool | Recovery signal | Call |
|---|---|---|
| Zabbix | `value=0` recovery event, or `r_eventid ≠ 0` on the problem | `event.get {"value":0}` / `problem.get` |
| Nagios | host back to `2` (UP) — i.e. gone from the DOWN set | `statusjson.cgi?query=hostlist` |
| NetXMS | alarm `state = 2` (terminated) | `GET /v1/alarms` |
| Centreon | resource status back to `OK`/`UP`, or no longer an unhandled problem | `monitoring/resources` |
| iTop | `operational_status` `resolved`/`closed` + `resolution_date` | `core/get` on `Incident` |

The collector already **sees** these — it filters them out (`state == 2`,
`status not in CRITICAL/UNKNOWN/DOWN`, …) instead of turning them into a
resolve call. Closing the loop means: on each poll, take the incidents this
tool has open in the dashboard (`GET /api/alerts/open` today — there is no
filtered incident listing yet, so this needs one) and, for any whose problem is
no longer reported, call `PATCH /api/incidents/{id}/resolve` with the tool's own
recovery timestamp —
which also fills `downtime_minutes` and `mttr_minutes` correctly rather than
from the moment the operator clicked.

**Gap 2 — `cause_category`/`cause_label` are always `None`.** `dim_cause` is
only ever populated by the seed data, so the cause breakdown reflects demo
rows, not reality. See [§10](#10-filling-dim_cause) for what each tool can map.

**Gap 3 — acknowledgement is ignored.** Every tool exposes it (`acknowledged`,
`problem_has_been_acknowledged`, `state=1`, `is_acknowledged`, an assigned
agent) and the dashboard has both the status and the endpoint, but no collector
reports it.

---

## 4. Zabbix

**Endpoint** `$ZABBIX_API_URL` = `http://zabbix-web:8080/api_jsonrpc.php`
(host: `http://localhost:8081/api_jsonrpc.php`) · JSON-RPC 2.0, `POST` only ·
version here: **7.0.29**.

**Auth** — `ZABBIX_API_TOKEN` (preferred, ≥ 5.4) or `user.login`, whose token
expires in ~30 min, so the collector logs in on every poll:

```bash
TOKEN=$(curl -s -H 'Content-Type: application/json-rpc' http://localhost:8081/api_jsonrpc.php \
  -d "{\"jsonrpc\":\"2.0\",\"method\":\"user.login\",\"params\":{\"username\":\"$ZABBIX_USER\",\"password\":\"$ZABBIX_PASSWORD\"},\"id\":1}" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["result"])')
```

**Calls worth knowing**

| Method | Returns | Use for |
|---|---|---|
| `event.get` `{"source":0,"value":1,"time_from":…,"selectHosts":["host","name"]}` | new PROBLEM events | **what the collector uses** |
| `event.get` `{"source":0,"value":0,"time_from":…}` | recovery events | closing incidents (gap 1) |
| `problem.get` `{"recent":false}` | problems open *right now*, with `r_eventid`, `acknowledged`, `severity` | reconciling open state, ack |
| `host.get` `{"selectInterfaces":["ip"]}` | inventory: `hostid`, `host`, `name`, `status`, IP | provisioning/auditing `dim_node` |
| `trigger.get` `{"selectTags":"extend"}` | trigger definitions + **tags** | cause mapping (gap 2) |
| `item.get` / `history.get` | metric values | capacity work, not incidents |

A real problem from this instance:

```json
{"eventid":"20","clock":"1785922526","severity":"3","acknowledged":"0",
 "name":"Linux: Zabbix agent is not available (for 3m)","r_eventid":"0"}
```

**Mapping**

| BI field | From | Transformation |
|---|---|---|
| `external_id` | `eventid` | `f"zabbix-event-{eventid}"` |
| `node_code` | `hosts[0].host`, then `hosts[0].name` | `match_node()`: code → name → IP |
| `severity` | `severity` 0–5 | `{0,1:low, 2,3:medium, 4:high, 5:critical}` |
| `detected_at` | `clock` (Unix s) | `datetime.fromtimestamp(clock, tz=utc)` |
| `description` | `name` | as-is |
| `status`, `acknowledged_at` | `acknowledged` = `"1"` | *not wired* → `acknowledge` call |
| `resolved_at` | `r_eventid ≠ 0` → that event's `clock` | *not wired* → `resolve` call |
| `cause_*` | trigger tags | *not wired*, see §10 |

Implementation: `etl/extract/zabbix.py`.

---

## 5. Nagios

**Endpoint** `$NAGIOS_API_URL` = `http://nagios` (host:
`http://localhost:8083`) · CGI, HTTP Basic (`$NAGIOS_USER`/`$NAGIOS_PASSWORD`),
optional `X-Auth-Token: $NAGIOS_API_KEY`.

Three JSON CGIs, all of them useful:

| CGI | Queries | Use for |
|---|---|---|
| `statusjson.cgi` | `hostlist`, `servicelist`, `host`, `service`, `hostcount`, `servicecount`, `programstatus` | current state — **what the collector uses** |
| `objectjson.cgi` | `hostlist`, `hostgrouplist`, `servicelist`, … | configuration/inventory, for `dim_node` |
| `archivejson.cgi` | `alertlist`, `alertcount`, `notificationlist`, `statechangelist` | history — real downtime and MTTR |

```bash
curl -s -u "$NAGIOS_USER:$NAGIOS_PASSWORD" -G http://localhost:8083/cgi-bin/statusjson.cgi \
  --data-urlencode 'query=hostlist'
# {"data":{"hostlist":{"localhost":2}}}   ← bitmask, not a count

curl -s -u "$NAGIOS_USER:$NAGIOS_PASSWORD" -G http://localhost:8083/cgi-bin/statusjson.cgi \
  --data-urlencode 'query=host' --data-urlencode 'hostname=localhost'
# last_state_change, plugin_output, problem_has_been_acknowledged, current_attempt…

curl -s -u "$NAGIOS_USER:$NAGIOS_PASSWORD" -G http://localhost:8083/cgi-bin/archivejson.cgi \
  --data-urlencode 'query=alertlist' --data-urlencode 'starttime=-86400' --data-urlencode 'endtime=0'
```

Host state is a **bitmask**: `1` PENDING, `2` UP, `4` DOWN, `8` UNREACHABLE.
Service states: `1` PENDING, `2` OK, `4` WARNING, `8` CRITICAL, `16` UNKNOWN.
Timestamps are **milliseconds**, not seconds.

**Mapping**

| BI field | From | Transformation |
|---|---|---|
| `external_id` | host name | `f"nagios-{host}-down"` — stable for the outage, so re-polls dedupe |
| `node_code` | host name | `match_node()` |
| `severity` | state | `4 → critical`, `8 → high`, others skipped |
| `detected_at` | **`now()`** | ⚠ should be `last_state_change / 1000` from `query=host`; using `now()` puts the incident in the hour it was polled, which skews the hourly distribution and `shift` |
| `description` | `plugin_output` (via `query=host`) | collector currently writes a generic label instead |
| `status`, `acknowledged_at` | `problem_has_been_acknowledged` | *not wired* |
| `resolved_at` | host back to `2`, `last_state_change` | *not wired* |

Only **hosts** are polled — `servicelist` is untouched, so a node that is up but
whose service is CRITICAL produces nothing.

Implementation: `etl/extract/nagios.py`.

---

## 6. NetXMS

**Endpoint** `$NETXMS_API_URL` = `http://netxms:8000` (host:
`http://localhost:8085`), no trailing `/v1` · REST v1 · bearer token.

```bash
TOKEN=$(curl -s -X POST http://localhost:8085/v1/login -H 'Content-Type: application/json' \
  -d "{\"username\":\"$NETXMS_USER\",\"password\":\"$NETXMS_PASSWORD\"}" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8085/v1/alarms
```

| Route | Returns |
|---|---|
| `GET /v1/alarms` | flat list: `id`, `severity`, `state`, `source`, `message`, `lastChangeTime`, `repeatCount` |
| `GET /v1/alarms/{id}` | the above plus `creationTime`, `originalSeverity`, `ackByUser`, `resolvedByUser`, `ruleDescription` |
| `GET /v1/objects` | **root objects only** (`Entire Network`, `Infrastructure Services`, …) |
| `GET /v1/objects/2/children` | the actual `Node` objects — id, name, status, IP, platform |
| `GET /v1/objects/{id}` | one object in full |
| `GET /v1/users` | accounts |

The trap: `/v1/objects` does **not** list nodes, so the collector's name lookup
misses and it falls back to the numeric `source` id, which then fails node
matching. Use `/v1/objects/2/children` to build the id → name map.

`severity` 0–4 = NORMAL, WARNING, MINOR, MAJOR, CRITICAL.
`state` 0 = outstanding, 1 = acknowledged, 2 = terminated.

**Mapping**

| BI field | From | Transformation |
|---|---|---|
| `external_id` | `id` | `f"netxms-alarm-{id}"` |
| `node_code` | `source` → object name | via `/v1/objects…` map, then `match_node()` |
| `severity` | `severity` | `{0:skip, 1,2:medium, 3:high, 4:critical}` |
| `detected_at` | `lastChangeTime`, else `creationTime` | ISO with `Z` → `+00:00`; ⚠ `lastChangeTime` moves on every repeat, so prefer `creationTime` for the true start |
| `description` | `message` | as-is |
| `status`, `acknowledged_at` | `state = 1` | *not wired* |
| `resolved_at` | `state = 2` | *currently just skipped* |
| `cause_*` | `categories`, `ruleDescription` | *not wired*, see §10 |

Implementation: `etl/extract/netxms.py`.

---

## 7. Centreon

**Endpoint** `$CENTREON_API_URL` = `http://centreon/centreon/api/latest`
(host: `http://localhost:8084/centreon/api/latest`) · REST v2 · version here:
**24.10.29**.

The path segment is the *product* version or the `latest` alias — `latest`,
`beta`, `v24.10` and `v24` all work, `/api/v2/` is a 404 by design.

```bash
TOKEN=$(curl -s -X POST http://localhost:8084/centreon/api/latest/login \
  -H 'Content-Type: application/json' \
  -d "{\"security\":{\"credentials\":{\"login\":\"$CENTREON_USER\",\"password\":\"$CENTREON_PASSWORD\"}}}" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["security"]["token"])')
curl -s -H "X-AUTH-TOKEN: $TOKEN" \
  'http://localhost:8084/centreon/api/latest/monitoring/resources?states=["unhandled_problems"]&statuses=["CRITICAL","UNKNOWN","DOWN"]&limit=100'
```

| Route | Use for |
|---|---|
| `monitoring/resources` | hosts **and** services in one list — **what the collector uses** |
| `monitoring/hosts`, `monitoring/services` | the same split by type |
| `monitoring/hosts/{id}/timeline` | state history → real downtime |
| `monitoring/downtimes`, `monitoring/acknowledgements` | planned downtime (exclude from availability), ack |
| `configuration/hosts`, `configuration/monitoring-servers` | inventory for `dim_node` |
| `platform/versions`, `platform/topology` | version and poller topology |

A resource carries: `type` (`host`/`service`), `id`, `name`, `alias`, `fqdn`,
`parent` (the host, for a service), `status.{code,name,severity_code}`,
`information` (plugin output), `last_status_change`, `duration`,
`is_acknowledged`, `is_in_downtime`, `monitoring_server_name`, `tries`.

**Mapping**

| BI field | From | Transformation |
|---|---|---|
| `external_id` | `type`, `id`, status | `f"centreon-{type}-{id}-{status}"` — stable while the state holds |
| `node_code` | `parent.name` (service) → `alias` → `name`, plus `fqdn` | `match_node()` |
| `severity` | `status.name` | `CRITICAL/DOWN → critical`, `UNKNOWN → high` |
| `detected_at` | `last_status_change` | `datetime.fromisoformat()` — already correct here |
| `description` | `information` | falls back to `"{STATUS} — {host} (Centreon)"` |
| `status`, `acknowledged_at` | `is_acknowledged` | *not wired* |
| `resolved_at` | resource no longer returned by the filter | *not wired* |
| `downtime_minutes` | `duration` / `last_status_change` | *not wired* — and `is_in_downtime` should exclude planned maintenance from availability |

Implementation: `etl/extract/centreon.py`.

---

## 8. iTop

**Endpoint** `$ITOP_API_URL` = `…/webservices/rest.php?version=1.0` ·
**POST only**, payload in a `json_data` **form field** (not a JSON body),
HTTP Basic auth. The account needs the *REST Services User* profile.

```bash
curl -s -X POST "$ITOP_API_URL" -u "$ITOP_USER:$ITOP_PASSWORD" \
  --data-urlencode 'json_data={"operation":"core/get","class":"Incident",
    "key":"SELECT Incident WHERE operational_status NOT IN (\"resolved\",\"closed\")",
    "output_fields":"ref,title,description,priority,start_date,functionalcis_list"}'
```

`{"operation":"list_operations"}` enumerates what the instance allows.
`code: 0` means success; anything else puts the reason in `message`.

Useful classes: `Incident`, `UserRequest`, `FunctionalCI` / `Server` /
`NetworkDevice` (the CMDB — the source for `dim_node.itop_ci_id`), `Organization`,
`Person`, `Team`.

Ticket fields that matter (sample in `endpoints.txt`): `ref` (`I-023404`),
`title`, `description` (HTML), `operational_status`, `status`, `priority`,
`urgency`, `impact`, `start_date`, `last_update`, `assignment_date`,
`resolution_date`, `close_date`, `tto`/`ttr` and their `sla_*_passed` flags,
`functionalcis_list`, `org_id_friendlyname`, `agent_id_friendlyname`.

**Mapping**

| BI field | From | Transformation |
|---|---|---|
| `external_id` | object key | `f"itop-incident-{key}"` |
| `itop_ticket_id` | `ref` | as-is → `fact_incident.itop_ticket_id` |
| `node_code` | `functionalcis_list[].functionalci_id` | matched against `dim_node.itop_ci_id`, then the CI's friendlyname |
| `node_code` (fallback) | `description` / `title` | regex `Hôte: <name>` and `… sur <name>`, quotes and a trailing `(IP)` stripped — because Zabbix-relayed tickets arrive with an **empty** `functionalcis_list` |
| `severity` | `priority` 1–4 | `{1:critical, 2:high, 3:medium, 4:low}` |
| `detected_at` | `start_date` | `"%Y-%m-%d %H:%M:%S"`, assumed UTC |
| `description` | `title` | HTML `description` is not used |
| `status`, `acknowledged_at` | `assignment_date`, `status=assigned` | *not wired* |
| `resolved_at` | `resolution_date` / `close_date` | *not wired* — tickets are simply excluded once resolved, so the dashboard incident stays open forever |
| `cause_*` | `service_id`, `servicesubcategory_id` | *not wired*, see §10 |

iTop is the one tool that already knows resolution times and SLA outcomes, and
it is the one where dropping them costs most: `tto`/`ttr` and `resolution_date`
map straight onto MTTR and the SLA panel.

Implementation: `etl/extract/itop.py`. Note the ETL **reads** iTop only — the
dashboard never creates or updates tickets.

---

## 9. Cross-tool field mapping

The same BI column, seen from all five tools:

| BI column | Zabbix | Nagios | NetXMS | Centreon | iTop |
|---|---|---|---|---|---|
| `external_id` | `zabbix-event-{eventid}` | `nagios-{host}-down` | `netxms-alarm-{id}` | `centreon-{type}-{id}-{status}` | `itop-incident-{key}` |
| host reference | `hosts[].host` / `.name` | hostlist key | object name via `source` | `parent.name`/`alias`/`name` + `fqdn` | CI id → friendlyname → regex on text |
| `severity` source | `severity` 0–5 | state bitmask 4/8 | `severity` 0–4 | `status.name` | `priority` 1–4 |
| → `critical` | 5 | 4 (DOWN) | 4 | CRITICAL, DOWN | 1 |
| → `high` | 4 | 8 (UNREACHABLE) | 3 | UNKNOWN | 2 |
| → `medium` | 2, 3 | — | 1, 2 | — | 3 |
| → `low` | 0, 1 | — | — | — | 4 |
| `detected_at` | `clock` (s) | ⚠ `now()` — should be `last_state_change` (ms) | `lastChangeTime` (ISO) | `last_status_change` (ISO) | `start_date` (naive) |
| `description` | `name` | ⚠ generic label — `plugin_output` available | `message` | `information` | `title` |
| ack signal | `acknowledged` | `problem_has_been_acknowledged` | `state = 1` | `is_acknowledged` | `assignment_date` |
| recovery signal | `value=0` / `r_eventid` | state back to `2` | `state = 2` | out of the problem filter | `resolution_date` |
| planned downtime | `maintenance_status` | `scheduled_downtime_depth` | maintenance mode | `is_in_downtime` | — |

Two conventions that must hold across all of them, or the KPIs drift:

1. **UTC everywhere.** Zabbix and Nagios give epochs (seconds / **milliseconds**);
   NetXMS and Centreon give ISO 8601 with `Z`; iTop gives a naive local string
   that the collector assumes is UTC — verify that against the iTop server's
   timezone before trusting MTTR.
2. **`external_id` stable, never time-based.** It is the dedupe key. Encode the
   problem's identity (alarm id, host + state), never the poll time.

---

## 10. Filling `dim_cause`

`dim_cause` is seeded with 13 labels in five categories — `Énergie`,
`Équipement`, `Liaison`, `Logiciel`, `Humain` (`database/02_seed.sql`) — and
`get_or_create_cause()` creates any new pair on the fly, so a collector can
send its own. What each tool can classify on:

| Tool | Field to classify on | How |
|---|---|---|
| Zabbix | trigger **tags** (`trigger.get {"selectTags":"extend"}`) | tag the triggers `cause=Énergie` / `label=…`; most direct route |
| Nagios | servicegroup / command name | map servicegroup → category |
| NetXMS | alarm `categories`, `ruleDescription` | categories are configured server-side |
| Centreon | service template or severity, `information` text | map template name → category |
| iTop | `service_id`, `servicesubcategory_id` | already a taxonomy — the closest match to `dim_cause` |

Cheapest first step, no tool configuration needed: keyword-match the message
text in `etl/transform/`, e.g. `onduleur|délestage|power` → `Énergie`,
`fibre|link down|liaison` → `Liaison`, and leave unmatched incidents with a
`NULL` `cause_id` rather than guessing.

---

## Verifying a tool end to end

```bash
# 1. the collector can authenticate and read
docker compose exec etl-worker python -c "
from datetime import datetime, timezone, timedelta
from extract import centreon           # or zabbix / nagios / netxms / itop
nodes=[{'code':'DED-001','name':'…','ip_address':'10.0.0.1'}]
print(centreon.fetch_events(nodes, datetime.now(timezone.utc)-timedelta(hours=1)))"

# 2. a full collection pass, per-tool counts
docker compose exec etl-worker python -c "
from pipelines.tasks import collect_supervision; print(collect_supervision.apply().get())"

# 3. what actually landed
docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "SELECT source_tool, status, COUNT(*), MIN(detected_at), MAX(detected_at)
     FROM fact_incident GROUP BY 1,2 ORDER BY 1,2;"
```

An empty result is usually **node matching**, not the API: hosts are matched to
`dim_node` by code, then name, then IP, and only against nodes whose
`dim_node.source_tool` equals the polling tool. Unmatched hosts are logged as
warnings by `skip_unmatched()` — read `docker compose logs etl-worker`.
