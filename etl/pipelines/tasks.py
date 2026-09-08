"""
Tâches Celery. Ce fichier est le seul endroit qui instancie les
connecteurs concrets à partir de `config.settings` — le reste du
pipeline (collector.py, transform/, load/) n'importe jamais un connecteur
par son nom, seulement via l'interface commune.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import psycopg2

from ..celery_app import app
from ..config import settings
from ..extract.api import centreon_client, itop_client, nagios_client, netxms_client, nsp_client, zabbix_client
from ..extract.db import centreon_db_reader, itop_db_reader, nagios_db_reader, netxms_db_reader, zabbix_db_reader
from ..load import load_facts
from .collector import ToolConnectors, collect_all


def _build_connectors() -> dict[str, ToolConnectors]:
    connectors: dict[str, ToolConnectors] = {}

    if settings.zabbix.api_enabled and settings.zabbix.api_base_url:
        connectors["zabbix"] = ToolConnectors(
            name="zabbix",
            api_client=zabbix_client.ZabbixClient(
                settings.zabbix.api_base_url, settings.zabbix.api_user,
                settings.zabbix.api_password, settings.zabbix.verify_ssl,
            ),
            db_reader_module=zabbix_db_reader,
            tool_config=settings.zabbix,
        )

    if settings.itop.api_enabled and settings.itop.api_base_url:
        connectors["itop"] = ToolConnectors(
            name="itop",
            api_client=itop_client.ITopClient(
                settings.itop.api_base_url, settings.itop.api_user,
                settings.itop.api_password, settings.itop.verify_ssl,
            ),
            db_reader_module=itop_db_reader,
            tool_config=settings.itop,
        )

    if settings.netxms.api_enabled and settings.netxms.api_base_url:
        connectors["netxms"] = ToolConnectors(
            name="netxms",
            api_client=netxms_client.NetXMSClient(
                settings.netxms.api_base_url, settings.netxms.api_user,
                settings.netxms.api_password, settings.netxms.verify_ssl,
            ),
            db_reader_module=netxms_db_reader,
            tool_config=settings.netxms,
        )

    if settings.centreon.api_enabled and settings.centreon.api_base_url:
        connectors["centreon"] = ToolConnectors(
            name="centreon",
            api_client=centreon_client.CentreonClient(
                settings.centreon.api_base_url, settings.centreon.api_user,
                settings.centreon.api_password, settings.centreon.verify_ssl,
            ),
            db_reader_module=centreon_db_reader,
            tool_config=settings.centreon,
        )

    # Nagios : connecteur toujours instancié, le mode décide de ce qu'il fait réellement.
    connectors["nagios"] = ToolConnectors(
        name="nagios",
        api_client=nagios_client.NagiosClient(
            mode=settings.nagios_mode,
            base_url=settings.nagios.api_base_url,
            user=settings.nagios.api_user,
            password=settings.nagios.api_password,
            livestatus_host=settings.nagios.api_base_url,
            verify_ssl=settings.nagios.verify_ssl,
        ),
        db_reader_module=nagios_db_reader,
        tool_config=settings.nagios,
    )

    # NSP : idem, connecteur présent dès maintenant, activé une fois confirmé.
    if settings.nsp.api_base_url:
        connectors["nsp"] = ToolConnectors(
            name="nsp",
            api_client=nsp_client.NSPClient(
                mode=settings.nsp_fm_mode,
                base_url=settings.nsp.api_base_url,
                user=settings.nsp.api_user,
                password=settings.nsp.api_password,
                verify_ssl=settings.nsp.verify_ssl,
            ),
            db_reader_module=None,
            tool_config=settings.nsp,
        )

    return connectors


@app.task(name="etl.pipelines.tasks.collect_all_tools")
def collect_all_tools():
    conn = psycopg2.connect(settings.warehouse.dsn)
    try:
        collect_all(conn, _build_connectors())
    finally:
        conn.close()


@app.task(name="etl.pipelines.tasks.refresh_supervision_coverage")
def refresh_supervision_coverage():
    conn = psycopg2.connect(settings.warehouse.dsn)
    try:
        load_facts.refresh_supervision_coverage(conn, date.today())
    finally:
        conn.close()


@app.task(name="etl.pipelines.tasks.generate_monthly_report")
def generate_monthly_report():
    # Génération PDF/DOCX du rapport mensuel — dépend du service de
    # reporting du backend (report_service), volontairement hors
    # périmètre de l'ETL : ce module se contente de déclencher l'appel.
    from ..report_trigger import trigger_monthly_report  # voir README pipelines/

    trigger_monthly_report(datetime.now(timezone.utc))
