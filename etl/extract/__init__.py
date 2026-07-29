"""Real supervision-tool collectors.

Each module exposes `fetch_events(nodes, since) -> list[dict]` returning raw
events in the shape `transform.normalize.to_ingest_payload` expects. A
collector is enabled iff its endpoint env var is configured — see
`enabled_collectors()`.
"""

import config
from extract import centreon, itop, nagios, netxms, zabbix


def enabled_collectors() -> dict:
    """source_tool -> fetch_events, for every tool whose endpoint is configured."""
    collectors = {}
    if config.ZABBIX_API_URL:
        collectors["zabbix"] = zabbix.fetch_events
    if config.NAGIOS_API_URL:
        collectors["nagios"] = nagios.fetch_events
    if config.NETXMS_API_URL:
        collectors["netxms"] = netxms.fetch_events
    if config.CENTREON_API_URL:
        collectors["centreon"] = centreon.fetch_events
    if config.ITOP_API_URL:
        collectors["itop"] = itop.fetch_events
    return collectors
