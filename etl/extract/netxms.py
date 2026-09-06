"""
NetXMS collector — REST API v1.

Targets the NetXMS web API daemon v1 REST API: POST {url}/v1/login with
{"username", "password"} returns a bearer token (short-lived, not cached —
we log in on every poll, matching the zabbix/centreon collectors), which
authenticates GET {url}/v1/alarms — a flat list of
{id, severity, state, source, message, lastChangeTime}. `source` is the
numeric id of the object (usually a Node) the alarm was raised on, and has to
be resolved to a name and address before it can be matched to a node.

Resolution deliberately uses two endpoints. GET {url}/v1/objects returns the
object tree in one request, but what it actually contains depends on the
server's configuration: on the instances this was built against it yields only
the handful of root containers and no Nodes at all, so relying on it alone
means no alarm ever resolves and every one is skipped as unmatched — a silent
failure that reads like an empty CMDB. Ids it does not cover are therefore
fetched one at a time from GET {url}/v1/objects/{id} and cached in Redis
across polls (see the object identity cache below — without it a pass costs
one request per distinct alarm source, every five minutes, forever). An id
neither endpoint resolves falls back to matching on the raw number, which
normally misses and is logged and skipped like any other unknown host.

Not every alarm comes from a host: on the ANPTIC instance about one in eight
distinct sources is a BusinessService rather than a Node. Those are skipped
silently — see HOST_CLASSES.

Active alarms are polled, so an alarm that stays active keeps its (stable)
alarm id — the backend deduplicates open incidents on
(source_tool, external_id).

dim_node rows for the real inventory are created by provision_netxms_nodes.py;
without them every alarm is reported as an unmatched host.

Two extra signals beyond fetch_events(), same reasoning as Zabbix/Centreon —
"active alarms" undercounts what a NOC dashboard needs:

  * fetch_host_availability()   -> object status right now, independent of
                                    whether an alarm happens to be open
  * fetch_maintenance_windows() -> objects currently flagged as under
                                    maintenance

Both reuse the same /v1/objects listing fetch_events() already reads, so
they cost one extra request each per poll, not one per node. The exact field
names they rely on (`status`, `maintenance` / `isInMaintenanceMode`) are
**not** confirmed against a real ANPTIC response the way the alarms path is
— NetXMS has moved object status/maintenance representation across major
versions before. Check a raw GET /v1/objects/{id} on a node you know is down
and one you know is under maintenance before trusting either signal for a
KPI.
"""

import json
import logging
from datetime import datetime, timezone

import redis
import requests

import config
from extract.common import build_node_index, match_node, skip_unmatched
from transform.causes import classify

logger = logging.getLogger(__name__)

# NetXMS severities 0–4: NORMAL, WARNING, MINOR, MAJOR, CRITICAL
SEVERITY_MAP = {0: "low", 1: "medium", 2: "medium", 3: "high", 4: "critical"}

# NetXMS alarm states: 0=outstanding, 1=acknowledged, 2=terminated/resolved
TERMINATED_STATE = 2

# Object classes that stand for a piece of equipment, i.e. that a dim_node can
# plausibly exist for. Anything else raising an alarm (BusinessService,
# Container, ...) is not a host and is skipped without a warning.
HOST_CLASSES = {"Node", "Cluster", "MobileDevice", "AccessPoint", "Sensor", "Chassis"}

# DCI (Data Collection Item) *description* substrings used to recognize a
# performance metric, matched case-insensitively — NetXMS has no standard key
# scheme the way Zabbix does, only whatever label the template/policy author
# gave the DCI. NOT confirmed against a real ANPTIC NetXMS 5.0.8 response —
# same caveat as fetch_maintenance_windows() above: check a raw
# GET /v1/objects/{id}/data-collection on a node you know reports these before
# trusting fetch_operational_metrics() for a KPI. Override via
# config.NETXMS_DCI_NAME_PATTERNS (same shape) once confirmed.
DEFAULT_DCI_NAME_PATTERNS = {
    "cpu_pct": ["cpu"],
    "ram_pct": ["memory", "physical memory"],
    "bandwidth_in_bps": ["traffic in", "in octets", "rx bytes"],
    "bandwidth_out_bps": ["traffic out", "out octets", "tx bytes"],
    "latency_ms": ["ping", "response time", "icmp"],
    "packet_loss_pct": ["packet loss"],
}

# DCI listing per node is one request per node (no bulk "all DCIs" endpoint) —
# cached in Redis for the same reason as the object identity cache above: at
# ~1400 nodes that is 1400 extra requests a pass without it. DCI definitions
# change far less often than alarms, so the cache is keyed and expired the
# same way.
_DCI_LIST_KEY = "noc:netxms:dci_list:{}"

# ── object identity cache ───────────────────────────────────────────────────
# Resolving alarm sources is by far the most expensive part of a poll: because
# /v1/objects lists only the root containers (see the module docstring), each
# distinct source costs its own GET /v1/objects/{id}. On the ANPTIC instance
# that is ~1180 requests per pass, and with a five-minute interval ~340k
# requests a day spent re-reading names and IP addresses that essentially never
# change.
#
# Redis rather than a process-local dict: the worker runs with concurrency 2,
# so a local cache is duplicated per process and thrown away on every restart
# and redeploy — precisely when a cold pass is most expensive.
#
# Only successful resolutions are stored. Caching a failure would let one
# transient error hide a host for the whole TTL, and failures are rare enough
# that retrying next pass costs nothing.
_OBJECT_KEY = "noc:netxms:object:{}"

_redis = redis.Redis(
    host=config.REDIS_HOST,
    port=config.REDIS_PORT,
    decode_responses=True,
    socket_connect_timeout=2,
)


def _cached_object(source_id) -> tuple[str, str, str] | None:
    try:
        raw = _redis.get(_OBJECT_KEY.format(source_id))
    except redis.RedisError as exc:
        # Degrade to the uncached path rather than failing the poll: a Redis
        # outage should cost latency, not incidents.
        logger.warning("[netxms] object cache unavailable: %s", exc)
        return None
    if not raw:
        return None
    try:
        name, ip, klass = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return name, ip, klass


def _cache_object(source_id, resolved: tuple[str, str, str]) -> None:
    try:
        _redis.set(
            _OBJECT_KEY.format(source_id),
            json.dumps(resolved),
            ex=config.NETXMS_OBJECT_CACHE_TTL_S,
        )
    except redis.RedisError:
        pass


def _login() -> str:
    r = requests.post(
        f"{config.NETXMS_API_URL.rstrip('/')}/v1/login",
        json={"username": config.NETXMS_USER, "password": config.NETXMS_PASSWORD},
        timeout=config.HTTP_TIMEOUT_S,
    )
    r.raise_for_status()
    return r.json()["token"]


def _get(path: str, token: str) -> dict | list:
    r = requests.get(
        f"{config.NETXMS_API_URL.rstrip('/')}{path}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=config.HTTP_TIMEOUT_S,
    )
    r.raise_for_status()
    return r.json()


def _as_list(payload: dict | list, key: str) -> list:
    return payload.get(key, []) if isinstance(payload, dict) else payload


def _object_ip(obj: dict) -> str:
    """A Node's primary address — `ipAddress` is {family, address, prefixLength}."""
    addr = obj.get("ipAddress")
    if isinstance(addr, dict):
        return addr.get("address", "")
    return addr or ""


def _resolve_source(source_id, token: str, cache: dict) -> tuple[str, str, str]:
    """(name, ip, class) for an alarm's source object, "" for any part unknown.

    Only called for ids the /v1/objects listing didn't cover. Three layers, in
    order: the per-poll dict (many alarms share one source), the Redis cache
    (see above — this is what removes the ~1180 requests a pass), and finally
    the server.
    """
    if source_id in cache:
        return cache[source_id]

    resolved = _cached_object(source_id)
    if resolved is None:
        resolved = ("", "", "")
        try:
            obj = _get(f"/v1/objects/{source_id}", token)
            if isinstance(obj, dict):
                resolved = (obj.get("name", ""), _object_ip(obj), obj.get("class", ""))
                if resolved[0]:
                    _cache_object(source_id, resolved)
        except requests.RequestException as exc:
            logger.warning("[netxms] could not resolve object %s: %s", source_id, exc)

    cache[source_id] = resolved
    return resolved


def fetch_events(nodes: list[dict]) -> list[dict]:
    token = _login()

    objects = _as_list(_get("/v1/objects", token), "objects")
    listed = {
        obj.get("id"): (obj.get("name", ""), _object_ip(obj), obj.get("class", ""))
        for obj in objects
    }

    alarms = _as_list(_get("/v1/alarms", token), "alarms")

    index = build_node_index(nodes)
    resolved_cache: dict = {}
    results = []
    for alarm in alarms:
        if int(alarm.get("state", 0)) == TERMINATED_STATE:
            continue
        severity_raw = int(alarm.get("severity", alarm.get("currentSeverity", 1)))
        if severity_raw == 0:  # NORMAL — not an incident
            continue
        source_id = alarm.get("source") or alarm.get("sourceObjectId")
        name, ip, klass = listed.get(source_id) or _resolve_source(
            source_id, token, resolved_cache
        )
        # Alarms are also raised on objects that are not hosts at all — a
        # BusinessService going to "failed" is the usual one. They can never
        # match a dim_node, so they are dropped quietly: warning about them
        # would tell the operator to provision something unprovisionable,
        # every poll, for as long as the service stays down.
        if klass and klass not in HOST_CLASSES:
            continue
        host = name or str(source_id or "")
        node_code = match_node(nodes, host, ip, index=index)
        if node_code is None:
            skip_unmatched("netxms", host)
            continue
        detected_raw = alarm.get("lastChangeTime") or alarm.get("creationTime")
        if isinstance(detected_raw, str):
            detected = datetime.fromisoformat(detected_raw.replace("Z", "+00:00"))
        elif detected_raw is not None:
            detected = datetime.fromtimestamp(int(detected_raw), tz=timezone.utc)
        else:
            detected = datetime.now(timezone.utc)
        message = alarm.get("message") or "Alarme NetXMS"
        category, label = classify(message)
        results.append(
            {
                "node_code": node_code,
                "source_tool": "netxms",
                "external_id": f"netxms-alarm-{alarm.get('id')}",
                "severity": SEVERITY_MAP.get(severity_raw, "medium"),
                "detected_at": detected.isoformat(),
                "description": message,
                "cause_category": category,
                "cause_label": label,
            }
        )
    return results


def fetch_host_availability(nodes: list[dict]) -> list[dict]:
    """Object status right now, independent of any open alarm.

    A node can be effectively down (connection lost) without necessarily
    having a currently-active alarm for it — an alarm can be acknowledged
    and treated as handled elsewhere, or the status flag can lag/lead the
    alarm depending on how the server's thresholds are configured. This
    reads the same /v1/objects listing fetch_events() already fetches, so
    it's one extra request per poll, not one per node.
    """
    token = _login()
    objects = _as_list(_get("/v1/objects", token), "objects")

    index = build_node_index(nodes)
    results = []
    for obj in objects:
        klass = obj.get("class", "")
        if klass and klass not in HOST_CLASSES:
            continue
        name = obj.get("name", "")
        ip = _object_ip(obj)
        host = name or str(obj.get("id", ""))
        node_code = match_node(nodes, host, ip, index=index)
        if node_code is None:
            skip_unmatched("netxms", host)
            continue
        # status: 0=NORMAL..4=CRITICAL, same scale as alarm severity. Treat
        # MINOR (2) and above as down — matches the threshold fetch_events()
        # effectively uses via alarm severity_raw.
        status_raw = obj.get("status")
        if status_raw is None:
            status = "unknown"
        elif int(status_raw) >= 2:
            status = "down"
        else:
            status = "up"
        results.append(
            {
                "node_code": node_code,
                "source_tool": "netxms",
                "status": status,
                "error": None,
                "checked_at": datetime.now(tz=timezone.utc).isoformat(),
            }
        )
    return results


def fetch_maintenance_windows(nodes: list[dict]) -> list[dict]:
    """Objects NetXMS currently flags as under maintenance.

    NetXMS exposes maintenance as a per-object on/off flag rather than a
    scheduled window with start/end times the way Zabbix or Nagios do — there
    is no active_since/active_till to report here, only that maintenance is
    on right now. Field name assumed as `maintenance`, with `isInMaintenanceMode`
    tried as a fallback; confirm the real one on your server (see module
    docstring) before relying on this for a KPI.
    """
    token = _login()
    objects = _as_list(_get("/v1/objects", token), "objects")

    index = build_node_index(nodes)
    results = []
    for obj in objects:
        klass = obj.get("class", "")
        if klass and klass not in HOST_CLASSES:
            continue
        if not (obj.get("maintenance") or obj.get("isInMaintenanceMode")):
            continue
        name = obj.get("name", "")
        ip = _object_ip(obj)
        host = name or str(obj.get("id", ""))
        node_code = match_node(nodes, host, ip, index=index)
        if node_code is None:
            skip_unmatched("netxms", host)
            continue
        results.append(
            {
                "node_code": node_code,
                "source_tool": "netxms",
                "maintenance_name": "Maintenance NetXMS",
                "active_since": None,
                "active_till": None,
            }
        )
    return results


def _cached_dci_list(node_obj_id, token: str) -> list[dict]:
    try:
        raw = _redis.get(_DCI_LIST_KEY.format(node_obj_id))
        if raw:
            return json.loads(raw)
    except (redis.RedisError, ValueError, TypeError) as exc:
        logger.warning("[netxms] DCI list cache read failed for %s: %s", node_obj_id, exc)

    try:
        payload = _get(f"/v1/objects/{node_obj_id}/data-collection", token)
    except requests.RequestException as exc:
        logger.warning("[netxms] could not list DCIs for object %s: %s", node_obj_id, exc)
        return []
    dcis = _as_list(payload, "dciList") or _as_list(payload, "items") or []
    try:
        _redis.set(
            _DCI_LIST_KEY.format(node_obj_id),
            json.dumps(dcis),
            ex=config.NETXMS_OBJECT_CACHE_TTL_S,
        )
    except redis.RedisError:
        pass
    return dcis


def _metric_name_for_dci(description: str, patterns: dict) -> str | None:
    lowered = (description or "").lower()
    for name, needles in patterns.items():
        if any(needle in lowered for needle in needles):
            return name
    return None


def fetch_operational_metrics(nodes: list[dict]) -> list[dict]:
    """Latest CPU / RAM / bandwidth / latency / packet-loss DCI value per node.

    Iterates every Node/Cluster object (same /v1/objects listing fetch_events()
    already reads), lists its DCIs (cached — see _DCI_LIST_KEY above), matches
    each DCI's description against DEFAULT_DCI_NAME_PATTERNS, and reads the
    latest value for the ones that match via
    GET /v1/objects/{id}/data-collection/{dciId}/values/latest.

    Cost: one DCI-list request per node on a cold cache (or cache miss), plus
    one values request per *matched* DCI (typically 3-6 per node, not every
    DCI it has) — bounded, unlike a naive per-DCI-per-poll history fetch.
    Endpoint paths are NOT confirmed against a real NetXMS 5.0.8 response
    (NetXMS's REST API has changed data-collection endpoints across major
    versions more than once) — verify both paths against your instance first;
    on a mismatch this fails closed (logs and returns nothing) rather than
    raising and taking down the rest of the poll.
    """
    token = _login()
    objects = _as_list(_get("/v1/objects", token), "objects")
    patterns = getattr(config, "NETXMS_DCI_NAME_PATTERNS", DEFAULT_DCI_NAME_PATTERNS)

    index = build_node_index(nodes)
    results = []
    for obj in objects:
        klass = obj.get("class", "")
        if klass and klass not in HOST_CLASSES:
            continue
        name = obj.get("name", "")
        ip = _object_ip(obj)
        host = name or str(obj.get("id", ""))
        node_code = match_node(nodes, host, ip, index=index)
        if node_code is None:
            skip_unmatched("netxms", host)
            continue

        obj_id = obj.get("id")
        for dci in _cached_dci_list(obj_id, token):
            metric_name = _metric_name_for_dci(dci.get("description", ""), patterns)
            if metric_name is None:
                continue
            dci_id = dci.get("id")
            try:
                latest = _get(
                    f"/v1/objects/{obj_id}/data-collection/{dci_id}/values/latest", token
                )
            except requests.RequestException as exc:
                logger.warning(
                    "[netxms] could not read latest value for DCI %s on %s: %s",
                    dci_id, obj_id, exc,
                )
                continue
            value = latest.get("value") if isinstance(latest, dict) else None
            if value is None:
                continue
            try:
                value = float(value)
            except (TypeError, ValueError):
                continue
            results.append(
                {
                    "node_code": node_code,
                    "source_tool": "netxms",
                    "metric": metric_name,
                    "value": value,
                    "unit": dci.get("unit"),
                    "collected_at": datetime.now(tz=timezone.utc).isoformat(),
                }
            )
    return results