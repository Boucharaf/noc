# Database Schema

PostgreSQL 15. Schema defined in `database/01_schema.sql`, demo data in the
generated `database/02_seed.sql` (see [Regenerating the dataset](#regenerating-the-dataset)).
Both run automatically via `docker-entrypoint-initdb.d` on a **fresh** `pgdata`
volume only.

## Table of Contents

- [Entity relationship overview](#entity-relationship-overview)
- [Dimension tables](#dimension-tables)
- [Fact table](#fact-table)
- [Materialized view](#materialized-view)
- [Indexes](#indexes)
- [Regenerating the dataset](#regenerating-the-dataset)

---

## Entity relationship overview

```
dim_region ──< dim_locality ──< dim_node ──< fact_incident >── dim_cause
                                                  │
                                            dim_user ──< push_subscription
                                            (dashboard accounts; each can
                                            have N push subscriptions, one
                                            per device/browser)

mv_kpi_node_monthly  (materialized view, aggregates fact_incident
                       joined through dim_node/dim_locality/dim_region,
                       one row per month × node)
```

- `dim_region` 1—N `dim_locality` 1—N `dim_node` 1—N `fact_incident`
- `dim_cause` 1—N `fact_incident` (nullable — an incident may have no
  categorized cause yet)
- `dim_user` is standalone with respect to the incident/network hierarchy
  (dashboard login accounts), but is the parent of `push_subscription`
  (one row per browser/device a user has granted push permission on).

## Dimension tables

### `dim_region`

| Column | Type | Notes |
|---|---|---|
| `id` | `SERIAL PK` | |
| `code` | `VARCHAR(10)` | unique |
| `name` | `VARCHAR(100)` | e.g. "Centre", "Hauts-Bassins" |
| `created_at` | `TIMESTAMP` | default `NOW()` |

### `dim_locality`

| Column | Type | Notes |
|---|---|---|
| `id` | `SERIAL PK` | |
| `region_id` | `INTEGER FK → dim_region` | |
| `code` | `VARCHAR(10)` | unique |
| `name` | `VARCHAR(150)` | e.g. "Ouagadougou" |
| `latitude`, `longitude` | `DECIMAL(9,6)` | nullable; drives the supervision map |
| `population` | `INTEGER` | default 0 |
| `created_at` | `TIMESTAMP` | default `NOW()` |

### `dim_node`

Represents a monitored network element (router, switch, VSAT terminal, etc).

| Column | Type | Notes |
|---|---|---|
| `id` | `SERIAL PK` | |
| `locality_id` | `INTEGER FK → dim_locality` | |
| `code` | `VARCHAR(20)` | unique, e.g. `OUA-012` |
| `name` | `VARCHAR(200)` | |
| `node_type` | `VARCHAR(50)` | e.g. router/switch |
| `ip_address` | `INET` | nullable |
| `source_tool` | `VARCHAR(20)` | `CHECK IN ('zabbix','nagios','netxms','centreon')` — which supervision tool owns this node |
| `itop_ci_id` | `VARCHAR(50)` | nullable — linked iTop CMDB CI, if any |
| `is_active` | `BOOLEAN` | default `TRUE`; the ETL collectors only match against active nodes |
| `created_at` | `TIMESTAMP` | default `NOW()` |

### `dim_cause`

| Column | Type | Notes |
|---|---|---|
| `id` | `SERIAL PK` | |
| `category` | `VARCHAR(50)` | e.g. Énergie, Équipement, Liaison, Logiciel, Humain |
| `label` | `VARCHAR(150)` | specific cause text |
| | | `UNIQUE(category, label)` |

Rows are created lazily on ingest (`incident_service.get_or_create_cause`) —
there's no fixed seed list beyond what `generate_seed.py` and live ingestion produce.

### `dim_user`

Dashboard login accounts (cahier des charges §10.1: admin / analyst / noc_agent).

| Column | Type | Notes |
|---|---|---|
| `id` | `SERIAL PK` | |
| `username` | `VARCHAR(50)` | unique |
| `full_name` | `VARCHAR(150)` | |
| `role` | `VARCHAR(20)` | `CHECK IN ('admin','analyst','noc_agent')`, default `noc_agent` |
| `password_hash` | `VARCHAR(100)` | bcrypt |
| `pin_hash` | `VARCHAR(64)` | unique, nullable — **SHA-256** of the 4-digit PIN |
| `is_active` | `BOOLEAN` | default `TRUE` |
| `last_login_at` | `TIMESTAMP` | nullable, updated on successful login |
| `created_at` | `TIMESTAMP` | default `NOW()` |

> **Why `pin_hash` is SHA-256, not bcrypt:** PIN login needs to look a user up
> *by hash value* in one query (`WHERE pin_hash = :hash`); bcrypt's per-hash
> random salt makes that impossible without iterating every user and calling
> `checkpw` on each. A 4-digit PIN doesn't carry enough entropy to benefit from
> adaptive hashing anyway, so a fast deterministic hash is the right tradeoff
> here — the primary password still uses bcrypt.

### `push_subscription`

Web Push subscriptions (one row per browser/device a `dim_user` has granted
notification permission on) — see
[integrations.md#web-push-browserpwa](integrations.md#web-push-browserpwa).

| Column | Type | Notes |
|---|---|---|
| `id` | `SERIAL PK` | |
| `user_id` | `INTEGER FK → dim_user` | |
| `endpoint` | `TEXT` | unique — the push service URL for this subscription (e.g. an `fcm.googleapis.com/...` URL); re-subscribing the same device upserts by this column |
| `p256dh` | `TEXT` | subscription's public key, for message encryption |
| `auth` | `TEXT` | subscription's auth secret, for message encryption |
| `created_at` | `TIMESTAMP` | default `NOW()` |

Pruned automatically by `push_service.py` when a delivery attempt gets a
`404`/`410` back (the browser dropped the subscription — uninstalled,
permission revoked).

## Fact table

### `fact_incident`

| Column | Type | Notes |
|---|---|---|
| `id` | `BIGSERIAL PK` | |
| `node_id` | `INTEGER FK → dim_node` | required |
| `cause_id` | `INTEGER FK → dim_cause` | nullable |
| `itop_ticket_id` | `VARCHAR(50)` | nullable — set if `itop_auto_ticket=true` on ingest |
| `external_id` | `VARCHAR(100)` | the supervision tool's own event/alert ID |
| `status` | `VARCHAR(20)` | `CHECK IN ('open','acknowledged','resolved','closed')`, default `open` |
| `severity` | `VARCHAR(20)` | `CHECK IN ('critical','high','medium','low')`, default `medium` |
| `detected_at` | `TIMESTAMP` | required, naive UTC |
| `acknowledged_at` | `TIMESTAMP` | nullable |
| `resolved_at` | `TIMESTAMP` | nullable |
| `mttr_minutes` | `INTEGER GENERATED ALWAYS AS ...` | **stored, computed**: `(resolved_at - detected_at)` in minutes |
| `downtime_minutes` | `INTEGER` | default 0; set explicitly by `resolve_incident` (not generated) |
| `shift` | `VARCHAR(20) GENERATED ALWAYS AS ...` | **stored, computed** from `detected_at`'s hour: `'noc'` (06–21h), `'terrain'` (07–16h — a subset, so `terrain` is effectively unreachable given the CASE order; only `noc` and `auto` occur in practice), else `'auto'` |
| `source_tool` | `VARCHAR(20)` | required, denormalized copy of the node's tool at ingest time |
| `description` | `TEXT` | nullable; resolution `notes` get appended here |
| `created_at` | `TIMESTAMP` | default `NOW()` |

> **Note on `shift`:** the `CASE` checks `BETWEEN 6 AND 21` before `BETWEEN 7
> AND 16`, so any hour in the first range short-circuits before the second is
> ever evaluated — `'terrain'` can never actually be produced by this
> expression as written. Only `'noc'` and `'auto'` appear in real data. Keep
> this in mind if adding shift-based reporting.

## Materialized view

### `mv_kpi_node_monthly`

Pre-aggregates `fact_incident` by month × node (joined up through
locality/region) — this is what every KPI/SLA endpoint actually queries
against, not `fact_incident` directly.

| Column | Meaning |
|---|---|
| `month` | `DATE_TRUNC('month', detected_at)` |
| `node_id`, `code`, `name`, `source_tool` | from `dim_node` |
| `locality_id`, `locality` | from `dim_locality` |
| `region` | from `dim_region` |
| `total_incidents` | `COUNT(*)` for that node/month |
| `resolved` | count where `status = 'resolved'` |
| `avg_mttr` | `AVG(mttr_minutes)` |
| `total_downtime` | `SUM(downtime_minutes)` |
| `availability_pct` | `100 - (total_downtime / (24*60*30) * 100)` — a fixed 30-day-month approximation, not the node's actual days-in-month |

Unique index on `(month, node_id)`.

**Refresh**: two mechanisms, per environment:

- **Nightly batch (spec §2.2)** — the Celery job `etl.refresh_kpi_view` runs
  `REFRESH MATERIALIZED VIEW CONCURRENTLY mv_kpi_node_monthly` daily at 02:00
  (`CONCURRENTLY` is possible thanks to the unique `(month, node_id)` index,
  so dashboard reads are never blocked).
- **Synchronous per-write (demo)** — when `SYNC_MV_REFRESH=true` (the
  default), every ingest/resolve also refreshes the view
  (`incident_service.refresh_kpi_view`) so newly ingested incidents show up
  instantly. Set it to `false` in production, where per-write refresh becomes
  a write-latency problem at real incident volume.

## Indexes

| Index | On | Purpose |
|---|---|---|
| `idx_incident_node` | `fact_incident(node_id)` | join to node |
| `idx_incident_detected` | `fact_incident(detected_at DESC)` | recency ordering (alerts feed) |
| `idx_incident_status` | `fact_incident(status)` | open/ack filtering |
| `idx_incident_month` | `fact_incident(DATE_TRUNC('month', detected_at), node_id)` | monthly aggregation support |
| `idx_node_locality` | `dim_node(locality_id)` | join to locality |
| `idx_locality_region` | `dim_locality(region_id)` | join to region |
| `idx_push_subscription_user` | `push_subscription(user_id)` | look up a user's subscriptions |
| (unique) | `mv_kpi_node_monthly(month, node_id)` | supports `REFRESH ... CONCURRENTLY`-style uniqueness and fast point lookups |
| (unique) | `push_subscription(endpoint)` | upsert-by-endpoint on re-subscribe |

## Regenerating the dataset

`database/generate_seed.py` produces `database/02_seed.sql` from scratch:
**13 regions**, **14 localities**, **~157 nodes** across Burkina Faso, **6
months** of synthetic incidents, and the 3 demo `dim_user` accounts (see the
[Authentication](../README.md#authentication) section of the README for
credentials).

```bash
python3 database/generate_seed.py   # rewrites database/02_seed.sql
docker compose down
docker volume rm noc_pgdata         # drops the existing DB so init scripts re-run
docker compose up -d
```

`01_schema.sql` and `02_seed.sql` only run on a **fresh** Postgres volume
(`docker-entrypoint-initdb.d` semantics) — dropping `noc_pgdata` is required
to force a reseed on an existing deployment.
