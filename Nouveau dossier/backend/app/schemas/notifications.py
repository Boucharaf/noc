"""Schémas des notifications navigateur."""
from __future__ import annotations

from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

from app.core.config import PUSH_ALLOWED_HOSTS


class PushSubscriptionKeys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=256)
    auth: str = Field(min_length=1, max_length=256)


class PushSubscriptionPayload(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2048)
    keys: PushSubscriptionKeys

    @field_validator("endpoint")
    @classmethod
    def _known_push_service(cls, value: str) -> str:
        """L'endpoint est une URL que le BACKEND appellera à chaque alerte.

        Acceptée telle quelle, elle ferait du serveur un relais vers le
        réseau interne (http://redis:6379, http://postgres:5432, les API des
        outils sources). Seuls les services de push des navigateurs sont
        admis, en HTTPS, sans identifiants ni port exotique.
        """
        parts = urlsplit(value)
        host = (parts.hostname or "").lower()
        if (
            parts.scheme != "https"
            or not host
            or parts.username
            or parts.password
            or parts.port not in (None, 443)
        ):
            raise ValueError("Abonnement refusé : URL de service de push invalide.")
        if not any(host == allowed or host.endswith(f".{allowed}") for allowed in PUSH_ALLOWED_HOSTS):
            raise ValueError(
                "Abonnement refusé : service de push non reconnu (PUSH_ALLOWED_HOSTS)."
            )
        return value


class PushUnsubscribePayload(BaseModel):
    """Le désabonnement n'a besoin que de l'endpoint, qui l'identifie.

    Distinct de PushSubscriptionPayload pour ne pas obliger l'appelant à
    inventer des clés de chiffrement dont il ne dispose plus : le
    navigateur les efface dès l'abonnement révoqué.
    """

    endpoint: str = Field(min_length=1, max_length=2048)


class VapidPublicKeyResponse(BaseModel):
    public_key: str
