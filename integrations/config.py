"""
Configuration des connecteurs, partagée par le collecteur et le backend.

UN OUTIL S'ACTIVE PAR SON URL. Il n'y a pas de liste d'outils à tenir à jour
quelque part : `<OUTIL>_API_URL` vide veut dire « pas configuré », et le
connecteur n'est simplement pas instancié. C'est le seul interrupteur, et il
est au même endroit que le reste de la configuration de l'outil — impossible
d'avoir une URL renseignée et un connecteur désactivé ailleurs sans le voir.

NetXMS, Nagios et Nokia NSP sont dans le périmètre du code mais pas dans
celui du laboratoire local : leurs connecteurs existent et s'activeront le
jour où l'agence renseignera leur URL, sans une ligne à écrire.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_OQL_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _oql_identifiers(variable: str, default: str = "") -> tuple[str, ...]:
    """Noms de classes ou d'attributs iTop, vérifiés avant d'entrer en OQL.

    integrations/itop.py les CONCATÈNE dans ses requêtes : une valeur comme
    « Incident WHERE 1=1 » en changerait le sens. Une valeur invalide est
    écartée et journalisée, plutôt que de faire tomber le collecteur.
    """
    kept = []
    for item in (part.strip() for part in os.getenv(variable, default).split(",")):
        if not item:
            continue
        if _OQL_IDENTIFIER.match(item):
            kept.append(item)
        else:
            logger.error("%s : « %s » ignoré, ce n'est pas un identifiant iTop", variable, item)
    return tuple(kept)


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


@dataclass(frozen=True, slots=True)
class ToolConfig:
    name: str
    url: str
    user: str
    password: str
    token: str
    verify_ssl: bool
    timeout_s: float

    @property
    def enabled(self) -> bool:
        return bool(self.url)


def tool_config(name: str) -> ToolConfig:
    prefix = name.upper()
    return ToolConfig(
        name=name,
        url=os.getenv(f"{prefix}_API_URL", "").strip(),
        user=os.getenv(f"{prefix}_API_USER", "").strip(),
        password=os.getenv(f"{prefix}_API_PASSWORD", ""),
        token=os.getenv(f"{prefix}_API_TOKEN", "").strip(),
        verify_ssl=_bool(f"{prefix}_VERIFY_SSL", True),
        timeout_s=_float(f"{prefix}_TIMEOUT_S", 20.0),
    )


# Ordre d'affichage sur l'écran Interopérabilité, et ordre de collecte.
# Les outils de supervision d'abord, l'ITSM ensuite : la fusion multi-outils
# rattache les tickets iTop à des équipements déjà connus.
TOOL_NAMES: tuple[str, ...] = ("zabbix", "centreon", "netxms", "nagios", "nsp", "itop")


def build_client(name: str):
    """Instancie le connecteur d'un outil, ou None s'il n'est pas configuré.

    L'import est fait ici, à l'intérieur de la fonction, et non en tête de
    module : un connecteur non configuré ne doit pas imposer ses dépendances.
    """
    config = tool_config(name)
    if not config.enabled:
        return None

    if name == "zabbix":
        from .zabbix import ZabbixClient

        return ZabbixClient(
            config.url, config.user, config.password, config.token,
            config.verify_ssl, config.timeout_s,
        )
    if name == "centreon":
        from .centreon import CentreonClient

        return CentreonClient(
            config.url, config.user, config.password, config.verify_ssl, config.timeout_s
        )
    if name == "itop":
        from .itop import ITopClient

        classes = _oql_identifiers("ITOP_TICKET_CLASSES", "Incident,UserRequest")
        event_field = next(iter(_oql_identifiers("ITOP_ZBX_EVENT_FIELD")), "")
        return ITopClient(
            config.url, config.user, config.password, config.verify_ssl,
            config.timeout_s, classes, event_field,
        )
    if name == "netxms":
        # DEUX ACCÈS, choisis par la forme de l'URL — le même interrupteur
        # unique que pour les autres outils. C'est ce que l'agence accorde qui
        # décide (compte sur l'API Web, ou compte de lecture sur la base), pas
        # le code : passer de l'un à l'autre ne change que cette variable.
        if config.url.startswith(("postgresql://", "postgres://")):
            from .netxms_db import NetXMSDatabaseClient

            return NetXMSDatabaseClient(
                config.url, config.user, config.password, config.verify_ssl, config.timeout_s
            )
        from .netxms import NetXMSClient

        return NetXMSClient(
            config.url, config.user, config.password, config.verify_ssl, config.timeout_s
        )
    if name == "nagios":
        from .nagios import NagiosClient

        return NagiosClient(
            config.url, config.user, config.password, config.verify_ssl, config.timeout_s
        )
    if name == "nsp":
        from .nsp import NSPClient

        return NSPClient(
            config.url, config.user, config.password, config.verify_ssl, config.timeout_s
        )
    raise ValueError(f"Outil inconnu : {name}")


def build_all_clients() -> dict:
    """Tous les connecteurs configurés, indexés par nom."""
    clients = {}
    for name in TOOL_NAMES:
        client = build_client(name)
        if client is not None:
            clients[name] = client
    return clients


def configured_tools() -> tuple[str, ...]:
    """Noms des outils dont l'URL est renseignée.

    Sert à l'écran Interopérabilité : un outil configuré mais jamais collecté
    doit apparaître comme « jamais collecté », pas disparaître de la page.
    """
    return tuple(name for name in TOOL_NAMES if tool_config(name).enabled)
