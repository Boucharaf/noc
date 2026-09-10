"""
Vocabulaire commun à tous les outils sources.

Ces structures sont le SEUL langage que connaissent le collecteur, le cache
Redis et le backend. Un connecteur traduit le dialecte de son outil vers
elles, et rien au-delà de `integrations/` ne doit jamais voir une sévérité
Zabbix numérique ou un état Centreon codé sur trois valeurs.

Pourquoi des dataclasses figées (`frozen`) : un objet normalisé traverse le
collecteur, la fusion multi-outils et la sérialisation Redis. Le rendre
immuable garantit qu'une étape ne peut pas en corriger discrètement une autre
— une correction doit produire un nouvel objet, donc être visible dans le code.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Vocabulaires normalisés
# ---------------------------------------------------------------------------
# Ordonnés du plus grave au moins grave : l'ordre est utilisé pour trier et
# pour choisir la sévérité retenue quand deux outils décrivent le même
# équipement (voir collector/merge.py).
SEVERITIES: tuple[str, ...] = ("critical", "high", "medium", "low", "info", "unknown")

# État d'un équipement tel qu'il est AFFICHÉ. « silent » n'est pas une valeur
# que remonte un outil : c'est nous qui la déduisons quand l'outil ne dit plus
# rien d'un équipement qu'il est censé superviser. Une supervision muette est
# une information, pas un « tout va bien ».
NODE_STATES: tuple[str, ...] = (
    "down",
    "degraded",
    "silent",
    "maintenance",
    "up",
    "unknown",
)

# Types de métriques que le NOC sait afficher. Un connecteur qui remonte autre
# chose voit sa mesure ignorée : mieux vaut une courbe absente qu'une courbe
# dont personne ne sait quelle unité elle porte.
METRIC_TYPES: tuple[str, ...] = (
    "latency_ms",
    "packet_loss_pct",
    "bandwidth_in_mbps",
    "bandwidth_out_mbps",
    "cpu_pct",
    "ram_pct",
    "availability_pct",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class Node:
    """Un équipement supervisé, vu par UN outil.

    `ref` est l'identifiant dans l'outil d'origine (hostid Zabbix, id
    Centreon, clé d'objet iTop). Il n'a de sens que couplé à `tool` : c'est
    le couple (tool, ref) qui identifie sans ambiguïté, jamais `ref` seul.
    """

    tool: str
    ref: str
    name: str
    # Nom TECHNIQUE, distinct du nom d'affichage — et c'est lui qui porte
    # l'identité.
    #
    # Zabbix sépare les deux : `host` est le nom technique (celui que l'agent
    # présente, celui qui figure dans les configurations), `name` est un
    # libellé que l'exploitant peut rendre lisible. Centreon fait de même avec
    # `name` et `alias`. Rapprocher les outils sur le libellé ne marche donc
    # pas : « noc-backend » côté CMDB et « noc-backend — Application NOC »
    # côté Zabbix désignent la même machine mais ne se ressemblent pas assez.
    #
    # Vaut `name` quand l'outil ne distingue pas les deux.
    hostname: str = ""
    ip: str | None = None
    state: str = "unknown"
    enabled: bool = True
    groups: tuple[str, ...] = ()
    # Site/localité déduits des groupes de l'outil quand la convention de
    # nommage le permet ; None sinon — on ne devine pas.
    site: str | None = None
    # Renseigné par les outils d'ITSM (iTop) uniquement.
    organisation: str | None = None
    node_type: str | None = None

    def key(self) -> str:
        return f"{self.tool}:{self.ref}"


@dataclass(frozen=True, slots=True)
class Alert:
    """Une alerte ACTIVE. Les alertes closes ne circulent jamais par ici :
    elles appartiennent à l'historique, qui reste chez l'outil source et se
    consulte à la demande (voir integrations/base.py::SourceClient.fetch_history).
    """

    tool: str
    ref: str
    severity: str
    message: str
    since: datetime
    node_ref: str | None = None
    node_name: str | None = None
    acknowledged: bool = False
    acknowledged_at: datetime | None = None
    # Ticket ITSM rattaché, quand l'outil le connaît (iTop).
    ticket_ref: str | None = None

    def key(self) -> str:
        return f"{self.tool}:{self.ref}"


@dataclass(frozen=True, slots=True)
class MetricPoint:
    """Un point de mesure. Jamais stocké chez nous : produit à la demande par
    une requête d'historique vers l'outil source, mis en cache Redis, expiré."""

    at: datetime
    value: float


@dataclass(frozen=True, slots=True)
class ToolHealth:
    """Résultat du contrôle de joignabilité d'un outil.

    `error` porte le message brut de l'outil ou de la couche réseau. Il est
    affiché tel quel à l'exploitant : une intégration qui échoue doit dire
    POURQUOI, sinon le diagnostic se fait à l'aveugle.
    """

    tool: str
    reachable: bool
    latency_ms: float | None = None
    version: str | None = None
    error: str | None = None
    checked_at: datetime = field(default_factory=_now)


@dataclass(frozen=True, slots=True)
class ToolSnapshot:
    """Ce qu'un connecteur rapporte d'un cycle de collecte."""

    health: ToolHealth
    nodes: tuple[Node, ...] = ()
    alerts: tuple[Alert, ...] = ()


def to_jsonable(value: Any) -> Any:
    """Sérialisation des dataclasses ci-dessus vers du JSON.

    Les `datetime` deviennent des chaînes ISO 8601 avec fuseau explicite. Sans
    le fuseau, une date relue serait interprétée en heure locale du lecteur —
    et un incident détecté à 23 h 40 UTC basculerait de jour selon le
    conteneur qui le relit.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    return value
