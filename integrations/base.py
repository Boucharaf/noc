"""
Contrat commun aux connecteurs, et plomberie HTTP partagée.

Un connecteur expose quatre méthodes, et rien d'autre ne le distingue :

    check()                      -> ToolHealth
    fetch_nodes()                -> list[Node]
    fetch_alerts()               -> list[Alert]
    fetch_history(...)           -> list[MetricPoint]

Les trois premières servent le CYCLE DE COLLECTE (collector/) : elles sont
appelées une fois toutes les 300 s, quoi qu'il arrive, et alimentent
l'instantané Redis.

La quatrième sert la FÉDÉRATION D'HISTORIQUE (backend/) : elle n'est appelée
que lorsqu'un exploitant ouvre une courbe, et son résultat est mis en cache.
C'est la méthode qui remplace l'ancienne table `metric_value` — au lieu de
recopier l'historique de Zabbix toutes les cinq minutes, on le lui demande
quand quelqu'un le regarde.

Le disjoncteur (`CircuitBreaker`) est ici et non dans chaque connecteur :
un outil injoignable doit cesser d'être sollicité de la même façon, qu'il
s'agisse de Zabbix ou de Nokia NSP.
"""
from __future__ import annotations

import abc
import logging
import time
from datetime import datetime
from typing import Any

import httpx

from .models import Alert, MetricPoint, Node, ToolHealth

logger = logging.getLogger(__name__)


class ToolUnavailable(RuntimeError):
    """Outil injoignable, en erreur, ou mal configuré.

    Toujours interceptée par l'appelant : dans le collecteur, un outil en
    panne ne doit jamais interrompre la collecte des autres ; dans le
    backend, il doit produire un message à l'écran, pas une erreur 500.
    """

    def __init__(self, tool: str, message: str):
        self.tool = tool
        super().__init__(f"{tool} : {message}")


class CircuitBreaker:
    """Disjoncteur : après `threshold` échecs consécutifs, refuse les appels
    pendant `cooldown_s` secondes.

    Sans lui, une source tombée transforme chaque ouverture de courbe en une
    attente du délai de garde complet, pour tous les opérateurs à la fois.
    Le disjoncteur rend l'échec IMMÉDIAT et lisible, ce qui vaut bien mieux
    qu'une page qui tourne trente secondes avant d'échouer quand même.
    """

    def __init__(self, threshold: int = 3, cooldown_s: float = 60.0):
        self.threshold = threshold
        self.cooldown_s = cooldown_s
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if time.monotonic() - self._opened_at >= self.cooldown_s:
            # Fin du repos : on laisse passer UN appel pour tester. S'il
            # échoue, record_failure rouvre immédiatement.
            self._opened_at = None
            self._failures = self.threshold - 1
            return False
        return True

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.threshold:
            self._opened_at = time.monotonic()

    def remaining_cooldown_s(self) -> float:
        if self._opened_at is None:
            return 0.0
        return max(0.0, self.cooldown_s - (time.monotonic() - self._opened_at))


class SourceClient(abc.ABC):
    """Base des connecteurs. Porte le client HTTP, le disjoncteur et la
    mesure de latence ; les sous-classes n'écrivent que la traduction propre
    à leur outil."""

    #: Nom court, identique à la clé de configuration et au préfixe Redis.
    name: str = "source"

    def __init__(
        self,
        base_url: str,
        user: str = "",
        password: str = "",
        verify_ssl: bool = True,
        timeout_s: float = 20.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.user = user
        self.password = password
        self.timeout_s = timeout_s
        self.breaker = CircuitBreaker()
        # Un seul client par connecteur : httpx garde les connexions ouvertes,
        # ce qui évite une poignée de main TLS complète à chaque cycle.
        self._client = httpx.AsyncClient(
            verify=verify_ssl,
            timeout=httpx.Timeout(timeout_s),
            follow_redirects=True,
            headers={"User-Agent": "NOC-RESINA/3.0 (collecteur)"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- plomberie ---------------------------------------------------------
    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Appel HTTP passant par le disjoncteur.

        Le disjoncteur est consulté ici et non dans `check()` : sinon un outil
        tombé continuerait d'être sollicité par les appels de données, et
        seul le contrôle de santé serait protégé.
        """
        if self.breaker.is_open:
            raise ToolUnavailable(
                self.name,
                f"disjoncteur ouvert, nouvelle tentative dans "
                f"{self.breaker.remaining_cooldown_s():.0f} s",
            )
        try:
            response = await self._client.request(method, url, **kwargs)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            self.breaker.record_failure()
            raise ToolUnavailable(
                self.name, f"HTTP {exc.response.status_code} sur {url}"
            ) from exc
        except httpx.HTTPError as exc:
            self.breaker.record_failure()
            raise ToolUnavailable(self.name, f"{type(exc).__name__} : {exc}") from exc
        self.breaker.record_success()
        return response

    async def _timed(self, coro) -> tuple[Any, float]:
        """Exécute et renvoie (résultat, latence en millisecondes).

        La latence est publiée sur l'écran Interopérabilité : c'est le premier
        signe qu'un outil source commence à souffrir, bien avant qu'il ne
        devienne franchement injoignable.
        """
        started = time.perf_counter()
        result = await coro
        return result, (time.perf_counter() - started) * 1000.0

    # -- contrat -----------------------------------------------------------
    @abc.abstractmethod
    async def check(self) -> ToolHealth:
        """Joignabilité et version. Ne doit jamais lever : un outil en panne
        se raconte par un ToolHealth(reachable=False, error=...)."""

    @abc.abstractmethod
    async def fetch_nodes(self) -> list[Node]:
        """Inventaire des équipements supervisés par cet outil."""

    @abc.abstractmethod
    async def fetch_alerts(self) -> list[Alert]:
        """Alertes ACTIVES uniquement. Voir models.Alert."""

    async def fetch_history(
        self,
        node_ref: str,
        metric_type: str,
        start: datetime,
        end: datetime,
    ) -> list[MetricPoint]:
        """Série temporelle, lue chez l'outil source à la demande.

        Le comportement par défaut est de ne rien renvoyer : tous les outils
        ne sont pas des sources de métriques (iTop est une CMDB, il n'en a
        aucune). Renvoyer une liste vide plutôt que lever laisse l'écran
        afficher « aucune mesure pour cette source » sans traiter le cas
        comme une panne.
        """
        return []

    # -- utilitaire pour les sous-classes ----------------------------------
    async def _health(self, probe) -> ToolHealth:
        """Enveloppe commune de `check()` : mesure la latence, convertit
        toute exception en ToolHealth non joignable."""
        try:
            version, latency = await self._timed(probe())
            return ToolHealth(
                tool=self.name, reachable=True, latency_ms=latency, version=version
            )
        except ToolUnavailable as exc:
            return ToolHealth(tool=self.name, reachable=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001 — un connecteur ne doit jamais
            # faire tomber le cycle de collecte, quelle que soit la surprise.
            logger.exception("Contrôle de santé %s : exception inattendue", self.name)
            return ToolHealth(
                tool=self.name, reachable=False, error=f"{type(exc).__name__} : {exc}"
            )
