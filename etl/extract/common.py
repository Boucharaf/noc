"""Shared helpers for the real supervision-tool collectors."""

import logging

logger = logging.getLogger(__name__)


def match_node(nodes: list[dict], *candidates: str) -> str | None:
    """Map a supervision-tool host reference onto a dim_node code.

    Tries, in order: exact node code, exact node name (case-insensitive),
    exact IP address. `nodes` is the active-node list for one source_tool
    (see pipelines/collector.py). Returns the node code, or None when the
    host isn't provisioned in the CMDB — the caller logs and skips it.
    """
    values = [c.strip() for c in candidates if c and c.strip()]
    if not values:
        return None
    by_code = {n["code"].lower(): n["code"] for n in nodes}
    by_name = {n["name"].lower(): n["code"] for n in nodes}
    by_ip = {n["ip_address"]: n["code"] for n in nodes if n.get("ip_address")}
    for value in values:
        code = (
            by_code.get(value.lower()) or by_name.get(value.lower()) or by_ip.get(value)
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
