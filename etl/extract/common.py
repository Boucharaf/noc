"""Shared helpers for the real supervision-tool collectors."""

import logging

logger = logging.getLogger(__name__)


def build_node_index(nodes: list[dict]) -> dict:
    """Precompute the by-code/by-name/by-ip lookup tables once per poll.

    match_node() used to rebuild these three dicts from `nodes` on every
    single call. Fine when a collector calls it once per fetch_events(), but
    wasteful once a collector calls it per-alarm/per-incident against a CMDB
    of hundreds of nodes (NetXMS, Centreon, Nagios all do now). Build this
    once at the top of fetch_events() and pass it as `index=` to skip the
    O(n) rebuild on every row.
    """
    return {
        "by_code": {n["code"].lower(): n["code"] for n in nodes},
        "by_name": {n["name"].lower(): n["code"] for n in nodes},
        "by_ip": {n["ip_address"]: n["code"] for n in nodes if n.get("ip_address")},
    }


def match_node(
    nodes: list[dict], *candidates: str, index: dict | None = None
) -> str | None:
    """Map a supervision-tool host reference onto a dim_node code.

    Tries, in order: exact node code, exact node name (case-insensitive),
    exact IP address. `nodes` is the active-node list for one source_tool
    (see pipelines/collector.py). Returns the node code, or None when the
    host isn't provisioned in the CMDB — the caller logs and skips it.

    Pass a precomputed `index` (see build_node_index) to avoid rebuilding
    the lookup tables on every call. Optional and backward compatible:
    existing call sites that don't pass it keep working exactly as before.
    """
    values = [c.strip() for c in candidates if c and c.strip()]
    if not values:
        return None
    idx = index or build_node_index(nodes)
    for value in values:
        code = (
            idx["by_code"].get(value.lower())
            or idx["by_name"].get(value.lower())
            or idx["by_ip"].get(value)
        )
        if code:
            return code
    return None


def skip_unmatched(tool: str, host: str) -> None:
    logger.warning(
        "[%s] host %r has no matching dim_node (by code, name, or IP) — "
        "provision it in the CMDB or align its code, skipping",
        tool,
        host,
    )