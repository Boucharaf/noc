"""Real supervision-tool collectors.

Each module exposes `fetch_events(nodes) -> list[dict]` returning raw events in
the shape `transform.normalize.to_ingest_payload` expects — the problems its
tool reports as open at that moment, so a pass that is missed or fails costs
nothing. A collector is enabled iff its endpoint env var is configured — see
`enabled_collectors()`.

Some collectors also expose signals beyond fetch_events() — host
availability, maintenance windows, operational metrics, resolved events —
because "the problems a tool currently has open" undercounts what a NOC
dashboard needs: a host can be unreachable with no trigger ever firing, or
sitting quietly in a maintenance window that suppresses events entirely.
See `enabled_extra_collectors()`.
"""

import logging

import config
from extract import centreon, itop, nagios, netxms, zabbix

logger = logging.getLogger(__name__)

# tool -> (config attr that must be set, fetch_events callable)
_COLLECTORS = {
    "zabbix": ("ZABBIX_API_URL", zabbix.fetch_events),
    "nagios": ("NAGIOS_API_URL", nagios.fetch_events),
    "netxms": ("NETXMS_API_URL", netxms.fetch_events),
    "centreon": ("CENTREON_API_URL", centreon.fetch_events),
    "itop": ("ITOP_API_URL", itop.fetch_events),
}

# tool -> {signal_name: callable}, only for tools that expose more than
# fetch_events(). Every callable takes `nodes` and returns list[dict].
_EXTRA_COLLECTORS = {
    "zabbix": {
        "host_availability": zabbix.fetch_host_availability,
        "maintenance_windows": zabbix.fetch_maintenance_windows,
        "operational_metrics": zabbix.fetch_operational_metrics,
    },
    "centreon": {
        "host_availability": centreon.fetch_host_availability,
        "maintenance_windows": centreon.fetch_maintenance_windows,
    },
    "nagios": {
        "service_availability": nagios.fetch_service_availability,
        "maintenance_windows": nagios.fetch_maintenance_windows,
    },
    "netxms": {
        "host_availability": netxms.fetch_host_availability,
        "maintenance_windows": netxms.fetch_maintenance_windows,
    },
    "itop": {
        "resolved_events": itop.fetch_resolved_events,
    },
}


def enabled_collectors() -> dict:
    """source_tool -> fetch_events, for every tool whose endpoint is configured."""
    collectors = {}
    for tool, (url_attr, fetch_events) in _COLLECTORS.items():
        if getattr(config, url_attr, None):
            collectors[tool] = fetch_events
        else:
            logger.info("[%s] disabled — %s not set", tool, url_attr)
    return collectors


def enabled_extra_collectors() -> dict:
    """source_tool -> {signal_name: callable}, restricted to enabled tools.

    Callers should treat each signal independently — a maintenance-windows
    poll failing for a tool shouldn't take down host_availability for that
    same tool, let alone every other tool's fetch_events().
    """
    enabled = enabled_collectors()
    return {
        tool: signals for tool, signals in _EXTRA_COLLECTORS.items() if tool in enabled
    }