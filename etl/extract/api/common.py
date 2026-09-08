"""
Utilitaires communs aux connecteurs API.

Chaque connecteur (zabbix_client.py, itop_client.py, ...) s'appuie sur
`build_session()` pour les retries/backoff, et sur `TokenCache` quand
l'API repose sur un token à durée de vie limitée (NSP, Centreon v2, ...).

Contrat commun à tous les connecteurs API de ce dossier :
    fetch_nodes()                -> list[dict]  (schéma NormalizedNode, voir transform/normalize_nodes.py)
    fetch_incidents(since)       -> list[dict]  (schéma NormalizedIncident)
    fetch_metrics(since)         -> list[dict]  (schéma NormalizedMetric)
    health_check()               -> bool

Ce contrat permet à pipelines/collector.py de traiter tous les outils de
façon identique, sans connaître leurs particularités internes.
"""
from __future__ import annotations

import time
from typing import Optional

import requests
from requests.adapters import HTTPAdapter, Retry


def build_session(verify_ssl: bool = True, total_retries: int = 3) -> requests.Session:
    session = requests.Session()
    session.verify = verify_ssl
    retries = Retry(
        total=total_retries,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.mount("http://", HTTPAdapter(max_retries=retries))
    return session


class TokenCache:
    """Cache simple d'un token/session-id avec expiration, pour éviter de
    ré-authentifier à chaque appel (Zabbix user.login, NSP bearer token,
    iTop peut aussi passer par une session HTTP classique)."""

    def __init__(self):
        self._token: Optional[str] = None
        self._expires_at: float = 0.0

    def get(self) -> Optional[str]:
        if self._token and time.time() < self._expires_at:
            return self._token
        return None

    def set(self, token: str, ttl_seconds: int):
        self._token = token
        self._expires_at = time.time() + max(0, ttl_seconds - 30)  # marge de sécurité


class ToolUnavailableError(RuntimeError):
    """Levée quand un outil est injoignable ou mal configuré.
    Ne doit JAMAIS remonter jusqu'à pipelines/collector.py sans être
    interceptée : un outil en panne ne doit pas bloquer les autres."""
