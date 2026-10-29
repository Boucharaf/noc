"""
Doublures partagées des tests du collecteur.

Elles suivent les interfaces RÉELLES — `SourceClient` et `SnapshotStore` —
plutôt que d'être réécrites à la main dans chaque test : une doublure écrite
pour une version passée de l'interface fait échouer le test sur un attribut
manquant, et l'échec ne dit plus rien du comportement testé.
"""
from __future__ import annotations

from integrations.base import SourceClient
from integrations.models import ToolHealth, to_jsonable


class FakeSource(SourceClient):
    """Outil source en mémoire.

    Hérite de `SourceClient` pour que le collecteur reconnaisse, comme pour un
    vrai connecteur, les méthodes facultatives NON surchargées (dernières
    valeurs, maintenances, ordres de travail) et ne les appelle pas.
    Le constructeur parent n'est pas appelé : il ouvrirait un client HTTP.
    """

    def __init__(self, tool="source", nodes=(), alerts=(), reachable=True, error=None):
        self.name = tool
        self.nodes = list(nodes)
        self.alerts = list(alerts)
        self.reachable = reachable
        self.error = error

    async def check(self):
        return ToolHealth(tool=self.name, reachable=self.reachable, error=self.error)

    async def fetch_nodes(self):
        return list(self.nodes)

    async def fetch_alerts(self):
        return list(self.alerts)


class MemoryStore:
    """`collector.state.SnapshotStore` en mémoire, méthode pour méthode.

    `diff_new_alerts` reproduit la règle réelle : le premier cycle mémorise
    les alertes sans les diffuser (pas d'envoi massif à la reprise).
    """

    def __init__(self):
        self.health = []
        self.sources = {}
        self.nodes = None
        self.alerts = None
        self.meta = None
        self.snapshot_written = False
        self.latest = None
        self.operations = None
        self.trend = []
        self.seen_alerts = None
        self.diffed = None
        self.published = []
        self.rollup = []

    async def write_snapshot(self, nodes, alerts, meta):
        self.snapshot_written = True
        self.nodes = nodes
        self.alerts = alerts
        self.meta = meta

    async def write_latest(self, latest):
        self.latest = latest

    async def write_operations(self, maintenance, work_orders):
        self.operations = (maintenance, work_orders)

    async def append_trend(self, point):
        self.trend.append(point)

    async def save_rollup(self, payload):
        self.rollup = payload

    async def load_rollup(self):
        return list(self.rollup)

    async def write_tool_health(self, health):
        self.health.append(health)

    async def write_source_data(self, tool, collection, records, collected_at):
        self.sources[(tool, collection)] = {
            "collected_at": collected_at.isoformat(),
            "records": to_jsonable(records),
        }

    async def read_source_data(self, tool, collection):
        return self.sources.get((tool, collection))

    async def diff_new_alerts(self, alerts):
        self.diffed = list(alerts)
        current = {alert.key() for alert in alerts}
        if self.seen_alerts is None:
            self.seen_alerts = current
            return []
        new = current - self.seen_alerts
        self.seen_alerts = current
        return [alert for alert in alerts if alert.key() in new]

    async def publish_new_alerts(self, alerts):
        self.published.extend(alerts)
