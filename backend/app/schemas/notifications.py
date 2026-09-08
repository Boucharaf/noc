"""Schémas des notifications navigateur."""
from __future__ import annotations

from pydantic import BaseModel


class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscriptionPayload(BaseModel):
    endpoint: str
    keys: PushSubscriptionKeys


class PushUnsubscribePayload(BaseModel):
    """Le désabonnement n'a besoin que de l'endpoint, qui l'identifie.

    Distinct de PushSubscriptionPayload pour ne pas obliger l'appelant à
    inventer des clés de chiffrement dont il ne dispose plus : le
    navigateur les efface dès l'abonnement révoqué.
    """

    endpoint: str


class VapidPublicKeyResponse(BaseModel):
    public_key: str
