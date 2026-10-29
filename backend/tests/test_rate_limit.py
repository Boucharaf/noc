"""Limitation de débit : middleware HTTP global (app.main), quotas par IP et
par utilisateur, fenêtre d'une minute dans Redis."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import rate_limit
from app.services import auth_service


class FakeAsyncRedis:
    """Exécute le script INCR + EXPIRE du module, compteur par clé."""

    def __init__(self):
        self.counts = {}

    async def eval(self, _script, _num_keys, key, _ttl):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]


def _client(monkeypatch, redis, read_per_min=1, user_read_per_min=10):
    monkeypatch.setattr(rate_limit, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(rate_limit, "RATE_LIMIT_READ_PER_MIN", read_per_min)
    monkeypatch.setattr(rate_limit, "RATE_LIMIT_USER_READ_PER_MIN", user_read_per_min)
    monkeypatch.setattr(rate_limit, "get_redis", lambda: redis)
    # Le client de test se présente comme le proxy nginx : X-Real-IP est cru.
    monkeypatch.setattr(rate_limit, "TRUSTED_PROXY_IPS", frozenset({"testclient"}))

    app = FastAPI()
    app.middleware("http")(rate_limit.rate_limit_middleware)

    @app.get("/api/items")
    def get_items():
        return {"items": []}

    @app.get("/health")
    def health():
        return {"ok": True}

    return TestClient(app)


def test_http_middleware_limits_each_ip(monkeypatch):
    client = _client(monkeypatch, FakeAsyncRedis())
    headers = {"X-Real-IP": "192.0.2.10"}

    assert client.get("/api/items", headers=headers).status_code == 200
    blocked = client.get("/api/items", headers=headers)
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == "60"
    assert client.get("/api/items", headers={"X-Real-IP": "192.0.2.11"}).status_code == 200
    # Hors /api/ : jamais limité (sondes de santé, fichiers statiques).
    assert client.get("/health", headers=headers).status_code == 200


def test_user_quota_is_counted_across_ips(monkeypatch):
    monkeypatch.setattr(
        auth_service, "decode_access_token", lambda token: {"sub": token}
    )
    client = _client(monkeypatch, FakeAsyncRedis(), read_per_min=10, user_read_per_min=1)

    def get(ip, user):
        return client.get(
            "/api/items", headers={"X-Real-IP": ip, "Authorization": f"Bearer {user}"}
        )

    assert get("192.0.2.10", "17").status_code == 200
    # Même compte depuis une autre adresse : le quota utilisateur s'applique.
    assert get("192.0.2.11", "17").status_code == 429
    assert get("192.0.2.11", "18").status_code == 200


def test_unavailable_redis_lets_requests_through(monkeypatch):
    class BrokenRedis:
        async def eval(self, *_args):
            raise ConnectionError("redis down")

    client = _client(monkeypatch, BrokenRedis())
    headers = {"X-Real-IP": "192.0.2.10"}

    # Mode ouvert assumé : la disponibilité du tableau de bord prime.
    assert client.get("/api/items", headers=headers).status_code == 200
    assert client.get("/api/items", headers=headers).status_code == 200
