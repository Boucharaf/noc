"""
Fédération d'historique — la pièce qui remplace l'ancienne table `metric_value`.

LE PRINCIPE. Zabbix conserve déjà ses mesures brutes et ses tendances horaires,
Centreon ses RRD. Les recopier toutes les cinq minutes, c'était payer deux fois
le même stockage et créer une seconde vérité qui dérive. Ici, quand un
exploitant ouvre la courbe de latence d'un équipement, on la demande à l'outil
qui la détient, et on met la réponse en cache.

CE QUE LE CACHE CHANGE. Dix opérateurs qui regardent le même graphe déclenchent
UNE requête vers Zabbix. C'est ce qui rend la fédération tenable : sans cache,
chaque ouverture d'écran serait un appel à la production.

DURÉE DE VIE DU CACHE, PROPORTIONNELLE À LA FENÊTRE. Une courbe sur 1 heure se
périme vite : la dernière mesure compte. Une courbe sur 6 mois ne change pas
d'une minute à l'autre — la garder une heure ne trompe personne et divise par
soixante les appels aux outils. D'où `_cache_ttl()`.

QUAND LA SOURCE EST INJOIGNABLE. On ne rend pas une courbe vide : une courbe
vide se lit comme « aucune donnée », c'est-à-dire comme un équipement muet, ce
qui est un diagnostic très différent de « Zabbix ne répond pas ». On lève
`HistoryUnavailable`, que la route transforme en message explicite à l'écran.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone

from integrations.base import ToolUnavailable
from integrations.config import build_client
from integrations.models import METRIC_TYPES

from app.db.redis_client import get_store

logger = logging.getLogger(__name__)

# Les connecteurs sont conservés d'un appel à l'autre : httpx garde ses
# connexions ouvertes, et Centreon garde son jeton. Les recréer à chaque
# requête imposerait une poignée de main TLS et une ré-authentification par
# ouverture de graphe.
_clients: dict[str, object] = {}


class HistoryUnavailable(RuntimeError):
    """L'outil source n'a pas pu répondre. À distinguer d'une série vide."""

    def __init__(self, tool: str, detail: str):
        self.tool = tool
        self.detail = detail
        super().__init__(f"{tool} : {detail}")


def _client(tool: str):
    if tool not in _clients:
        client = build_client(tool)
        if client is None:
            raise HistoryUnavailable(tool, "outil non configuré (URL absente)")
        _clients[tool] = client
    return _clients[tool]


async def aclose_all() -> None:
    """Ferme les connecteurs. Appelé à l'arrêt de l'application."""
    for client in _clients.values():
        try:
            await client.aclose()
        except Exception:  # noqa: BLE001 — un arrêt ne doit jamais échouer
            logger.debug("Fermeture du connecteur ignorée", exc_info=True)
    _clients.clear()


def _cache_ttl(start: datetime, end: datetime) -> int:
    """Durée de vie du cache, proportionnelle à la fenêtre demandée.

    Le rapport retenu est d'environ 1/60 de la fenêtre, borné : une courbe
    sur une heure vieillit d'une minute au plus, une courbe sur un an d'une
    heure au plus. Au-delà, l'exploitant verrait des données trop anciennes ;
    en deçà, le cache ne protégerait plus les outils sources.
    """
    window_s = max(60.0, (end - start).total_seconds())
    return int(min(3600, max(60, window_s / 60)))


def _fingerprint(tool: str, node_ref: str, metric_type: str,
                 start: datetime, end: datetime) -> str:
    """Clé de cache.

    Les bornes sont ARRONDIES au pas du cache avant d'entrer dans l'empreinte.
    Sans cet arrondi, deux opérateurs ouvrant le même graphe à une seconde
    d'écart produiraient deux clés différentes, et le cache ne servirait
    jamais — c'est le piège classique d'un cache indexé sur « maintenant ».
    """
    step = _cache_ttl(start, end)
    start_bucket = int(start.timestamp()) // step
    end_bucket = int(end.timestamp()) // step
    raw = f"{tool}|{node_ref}|{metric_type}|{start_bucket}|{end_bucket}|{step}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


async def fetch_series(
    tool: str,
    node_ref: str,
    metric_type: str,
    start: datetime,
    end: datetime,
) -> list[dict]:
    """Série temporelle d'un équipement, lue chez son outil source.

    Rend une liste de points `{"at": ISO 8601, "value": float}`, éventuellement
    vide si l'outil répond mais ne connaît pas cette métrique pour cet
    équipement. Lève `HistoryUnavailable` si l'outil n'a pas répondu.
    """
    if metric_type not in METRIC_TYPES:
        raise ValueError(f"Type de métrique inconnu : {metric_type}")

    store = get_store()
    fingerprint = _fingerprint(tool, node_ref, metric_type, start, end)

    cached = await store.get_history(fingerprint)
    if cached is not None:
        logger.debug("Historique servi par le cache (%s)", fingerprint)
        return cached

    try:
        points = await _client(tool).fetch_history(node_ref, metric_type, start, end)
    except ToolUnavailable as exc:
        raise HistoryUnavailable(tool, str(exc)) from exc
    except HistoryUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 — un connecteur qui surprend ne
        # doit pas produire une erreur 500 sans explication à l'écran.
        logger.exception("Historique %s : exception inattendue", tool)
        raise HistoryUnavailable(tool, f"{type(exc).__name__} : {exc}") from exc

    serialised = [
        {"at": point.at.astimezone(timezone.utc).isoformat(), "value": point.value}
        for point in points
    ]
    await store.set_history(fingerprint, serialised, _cache_ttl(start, end))
    logger.info(
        "Historique %s/%s/%s : %d point(s) lus chez la source",
        tool, node_ref, metric_type, len(serialised),
    )
    return serialised


async def fetch_node_series(
    node: dict,
    metric_type: str,
    start: datetime,
    end: datetime,
) -> dict:
    """Série d'un équipement du parc, en interrogeant les outils qui le voient.

    Un équipement fusionné est connu de plusieurs outils (`node["sources"]`).
    On les interroge dans l'ordre de préférence et on retient la PREMIÈRE
    réponse non vide, plutôt que de fusionner les séries : mélanger des
    mesures de deux sondes différentes sur une même courbe produirait des
    sauts que personne ne saurait interpréter.

    Les échecs sont rapportés dans `errors` sans faire échouer l'appel : si
    Zabbix est tombé mais que Centreon répond, l'exploitant voit sa courbe et
    l'indication que la source habituelle n'a pas répondu.
    """
    # Zabbix d'abord : c'est la source de métriques la plus riche du parc.
    order = ("zabbix", "centreon", "netxms", "nagios", "nsp")
    sources = node.get("sources") or {}

    errors: list[dict] = []
    for tool in order:
        ref = sources.get(tool)
        if not ref:
            continue
        try:
            points = await fetch_series(tool, ref, metric_type, start, end)
        except HistoryUnavailable as exc:
            errors.append({"tool": tool, "error": exc.detail})
            continue
        if points:
            return {
                "metric_type": metric_type,
                "source": tool,
                "points": points,
                "errors": errors,
            }

    return {
        "metric_type": metric_type,
        # Aucune source n'a de série. `source` à None dit explicitement
        # « personne ne mesure ça ici », ce qui n'est pas la même chose
        # qu'une série vide venant d'une source identifiée.
        "source": None,
        "points": [],
        "errors": errors,
    }


def resolve_window(period: str | None, start: datetime | None,
                   end: datetime | None) -> tuple[datetime, datetime]:
    """Fenêtre temporelle, depuis un raccourci ou des bornes explicites.

    Les raccourcis existent parce que 95 % des consultations portent sur l'une
    de ces cinq fenêtres, et les nommer permet au cache de les partager entre
    opérateurs — deux bornes saisies à la main ne tomberaient jamais dans le
    même seau.
    """
    now = datetime.now(timezone.utc)
    if start and end:
        return start, end

    windows = {
        "1h": timedelta(hours=1),
        "6h": timedelta(hours=6),
        "24h": timedelta(days=1),
        "7d": timedelta(days=7),
        "30d": timedelta(days=30),
        "90d": timedelta(days=90),
        "1y": timedelta(days=365),
    }
    return now - windows.get(period or "24h", timedelta(days=1)), now
