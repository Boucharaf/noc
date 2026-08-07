from pydantic import BaseModel


class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscriptionPayload(BaseModel):
    endpoint: str
    keys: PushSubscriptionKeys


class PushUnsubscribePayload(BaseModel):
    """Removing a subscription only needs its endpoint, which identifies it.

    Separate from PushSubscriptionPayload so callers are not made to invent
    encryption keys they do not have — the browser discards them once the
    subscription is gone, and requiring them here invited sending empty
    strings that the server would then have had to ignore.
    """

    endpoint: str


class VapidPublicKeyResponse(BaseModel):
    public_key: str
