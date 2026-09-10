"""
Connecteur NetXMS — lecture directe de la base PostgreSQL du serveur.

POURQUOI UN SECOND CONNECTEUR NETXMS. `netxms.py` parle à l'API Web ; celui-ci
lit la base. Les deux rendent les mêmes `Node` et `Alert` : rien au-delà de
`integrations/` ne sait lequel tourne. Le choix se fait par la forme de
NETXMS_API_URL (integrations/config.py) :

    https://…        → API Web (netxms-websvc), netxms.py
    postgresql://…   → base, ce fichier

C'est ce qui permet d'exploiter en local le dump de production restauré dans
`netxms-db`, puis de passer en production SANS modifier de code : seule change
la valeur de cette variable, selon ce que l'agence accorde — un compte sur
l'API, ou le compte de lecture décrit dans database/netxms_readonly_role.sql.

GARANTIES ENVERS LA BASE DE PRODUCTION :
  * chaque connexion est ouverte en lecture seule et avec un délai de garde,
    côté client ici, et doublée côté serveur par le rôle `noc_reader` ;
  * deux requêtes par cycle de collecte, jamais sur les tables de séries
    temporelles ;
  * aucune colonne secrète n'est lue (communautés SNMP, secrets d'agent).

CE QUE LA BASE NE DONNE PAS : l'historique des mesures. idata_* et tdata_*
sont des hypertables TimescaleDB, et un dump les restaure vides —
`fetch_history` reste donc celui, vide, de la classe de base.
"""
from __future__ import annotations

import ipaddress
import logging

from .base import SourceClient, ToolUnavailable
from .models import Alert, Node, ToolHealth
from .netxms import _OBJECT_STATE
from .normalize import epoch_to_dt, severity

logger = logging.getLogger(__name__)

# Le référentiel de sites de l'agence : la colonne `siteadmin_id` ajoutée à
# object_properties, qui pointe vers donnebase.siteadministratif. Ce n'est PAS
# du NetXMS standard — d'où la détection : sur une base qui ne l'a pas, ou si
# le compte de lecture n'y a pas droit (information_schema ne montre que les
# colonnes accessibles), le site retombe sur la ville de l'objet.
_SITE_REFERENTIAL_PROBE = """
SELECT count(*) = 2
FROM information_schema.columns
WHERE (table_schema = 'public' AND table_name = 'object_properties'
       AND column_name = 'siteadmin_id')
   OR (table_schema = 'donnebase' AND table_name = 'siteadministratif'
       AND column_name = 'nomsiteadministratif')
"""

_NODES_SQL = """
SELECT n.id,
       p.name,
       n.primary_name,
       n.primary_ip,
       p.status,
       p.city,
       {site_column} AS site,
       (SELECT array_agg(cp.name ORDER BY cp.name)
          FROM container_members cm
          JOIN object_properties cp ON cp.object_id = cm.container_id
         WHERE cm.object_id = n.id AND cp.is_deleted = 0) AS containers
FROM nodes n
JOIN object_properties p ON p.object_id = n.id
{site_join}
WHERE p.is_deleted = 0
"""

# Une alarme d'interface (« GigabitEthernet2 down ») a pour source l'objet
# INTERFACE, pas l'équipement : sans la remontée vers interfaces.node_id, un
# dixième des alarmes resteraient orphelines sur l'écran du NOC.
#
# État d'alarme : 0 en cours, 1 acquittée, 2 résolue, 3 terminée ; le bit
# 0x10 marque un acquittement « collant ». Seuls 0 et 1 sont actifs.
_ALERTS_SQL = """
SELECT a.alarm_id,
       a.alarm_state & 15 AS state,
       a.current_severity,
       a.message,
       a.creation_time,
       a.last_state_change_time,
       COALESCE(i.node_id, a.source_object_id) AS node_id,
       np.name
FROM alarms a
LEFT JOIN interfaces i ON i.id = a.source_object_id
LEFT JOIN object_properties np ON np.object_id = COALESCE(i.node_id, a.source_object_id)
WHERE (a.alarm_state & 15) IN (0, 1)
"""


def _first_line(exc: Exception) -> str:
    """Message d'erreur PostgreSQL sans ses lignes de contexte : il s'affiche
    tel quel sur l'écran Interopérabilité."""
    text = str(exc).strip()
    return text.splitlines()[0] if text else type(exc).__name__


def _valid_ip(value: str | None) -> str | None:
    # NetXMS écrit 0.0.0.0 pour « pas d'adresse » : la laisser passer ferait
    # fusionner entre eux tous les équipements sans IP.
    return value if value and value not in ("0.0.0.0", "::") else None


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value.strip())
        return True
    except ValueError:
        return False


class NetXMSDatabaseClient(SourceClient):
    name = "netxms"

    def __init__(
        self,
        dsn: str,
        user: str = "",
        password: str = "",
        verify_ssl: bool = True,
        timeout_s: float = 20.0,
    ):
        # `verify_ssl` n'a pas d'équivalent ici : le chiffrement d'une
        # connexion PostgreSQL se règle dans l'URL (?sslmode=verify-full).
        super().__init__(dsn, user, password, verify_ssl, timeout_s)
        self._site_referential: bool | None = None

    async def _query(self, sql: str) -> list[tuple]:
        """Une requête, sur une connexion ouverte pour elle.

        Pas de connexion persistante : à une requête toutes les cinq minutes,
        la garder ouverte n'économise rien et obligerait à gérer sa perte à
        chaque redémarrage de la base.
        """
        if self.breaker.is_open:
            raise ToolUnavailable(
                self.name,
                f"disjoncteur ouvert, nouvelle tentative dans "
                f"{self.breaker.remaining_cooldown_s():.0f} s",
            )
        try:
            # Importé ici : seul le collecteur ouvre ces connexions. Le backend
            # instancie ce connecteur pour l'historique, qui ne touche pas la
            # base, et n'embarque pas psycopg.
            import psycopg
        except ModuleNotFoundError as exc:
            raise ToolUnavailable(self.name, "psycopg absent de cette image") from exc

        try:
            conn = await psycopg.AsyncConnection.connect(
                self.base_url,
                user=self.user or None,
                password=self.password or None,
                connect_timeout=max(1, int(self.timeout_s)),
                application_name="noc-collecteur",
                autocommit=True,
                options=(
                    "-c default_transaction_read_only=on "
                    f"-c statement_timeout={int(self.timeout_s * 1000)}"
                ),
            )
            async with conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(sql)
                    rows = await cursor.fetchall()
        except psycopg.Error as exc:
            self.breaker.record_failure()
            raise ToolUnavailable(self.name, _first_line(exc)) from exc
        self.breaker.record_success()
        return rows

    async def check(self) -> ToolHealth:
        async def probe():
            rows = await self._query(
                "SELECT var_name, var_value FROM metadata "
                "WHERE var_name IN ('SchemaVersionMajor', 'SchemaVersionMinor')"
            )
            versions = dict(rows)
            if "SchemaVersionMajor" not in versions:
                raise ToolUnavailable(
                    self.name, "aucune version de schéma : est-ce bien une base NetXMS ?"
                )
            return (
                f"base, schéma {versions['SchemaVersionMajor']}."
                f"{versions.get('SchemaVersionMinor', '?')}"
            )

        return await self._health(probe)

    async def _uses_site_referential(self) -> bool:
        if self._site_referential is None:
            rows = await self._query(_SITE_REFERENTIAL_PROBE)
            self._site_referential = bool(rows and rows[0][0])
            logger.info(
                "netxms : référentiel de sites de l'agence %s",
                "utilisé" if self._site_referential else "absent, repli sur la ville",
            )
        return self._site_referential

    async def fetch_nodes(self) -> list[Node]:
        if await self._uses_site_referential():
            sql = _NODES_SQL.format(
                site_column="s.nomsiteadministratif",
                site_join=(
                    "LEFT JOIN donnebase.siteadministratif s "
                    "ON s.id_siteadministratif = p.siteadmin_id"
                ),
            )
        else:
            sql = _NODES_SQL.format(site_column="NULL", site_join="")

        nodes: list[Node] = []
        rows = await self._query(sql)
        for node_id, name, primary_name, ip, status, city, site, containers in rows:
            # Site : le référentiel de l'agence d'abord, sinon la ville saisie
            # dans NetXMS. Rien d'autre — un site deviné serait pire qu'absent.
            if not site and city and city.strip():
                site = city.strip().title()
            # `primary_name` est le nom DNS quand il existe, et l'adresse IP
            # sinon — c'est le cas de la plupart des nœuds de l'agence. Une IP
            # n'identifie pas un nom : le nom technique retombe alors sur le
            # nom de l'objet (OUAG-MDENP_ANPTIC-RT01).
            technical = primary_name if primary_name and not _is_ip(primary_name) else name
            nodes.append(
                Node(
                    tool=self.name,
                    ref=str(node_id),
                    name=name or primary_name or "(sans nom)",
                    hostname=technical or "",
                    ip=_valid_ip(ip),
                    state=_OBJECT_STATE.get(status, "unknown"),
                    enabled=status not in (6, 7),  # 6 non géré, 7 désactivé
                    # Les conteneurs NetXMS de l'agence sont des catégories
                    # (« Client », « Core ») plus que des lieux : ils restent
                    # des groupes et ne servent pas de site.
                    groups=tuple(containers or ()),
                    site=site or None,
                )
            )
        return nodes

    async def fetch_alerts(self) -> list[Alert]:
        alerts: list[Alert] = []
        for alarm_id, state, current_severity, message, created, changed, node_id, node_name in (
            await self._query(_ALERTS_SQL)
        ):
            since = epoch_to_dt(created)
            if since is None:
                continue
            acknowledged = state == 1
            alerts.append(
                Alert(
                    tool=self.name,
                    ref=str(alarm_id),
                    severity=severity("netxms", current_severity),
                    message=message or "(sans libellé)",
                    since=since,
                    node_ref=str(node_id) if node_id else None,
                    node_name=node_name,
                    acknowledged=acknowledged,
                    acknowledged_at=epoch_to_dt(changed) if acknowledged else None,
                )
            )
        return alerts
