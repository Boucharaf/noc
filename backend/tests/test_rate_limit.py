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


class FakeSyncRedis:
    """Juste ce qu'utilise le verrouillage après échecs (session_store)."""

    def __init__(self):
        self.values, self.ttls = {}, {}

    def incr(self, key):
        self.values[key] = int(self.values.get(key, 0)) + 1
        return self.values[key]

    def expire(self, key, seconds):
        self.ttls[key] = seconds

    def set(self, key, value, ex=None):
        self.values[key] = value
        self.ttls[key] = ex

    def delete(self, key):
        self.values.pop(key, None)
        self.ttls.pop(key, None)

    def ttl(self, key):
        return self.ttls.get(key, -2) if key in self.values else -2


def test_pin_is_locked_for_everyone_after_distributed_failures(monkeypatch):
    """INC-43 : une énumération du PIN répartie sur plusieurs IP est arrêtée."""
    from app.core import session_store

    monkeypatch.setattr(session_store, "redis_client", FakeSyncRedis())
    monkeypatch.setattr(session_store, "PIN_GLOBAL_MAX_FAILURES", 6)

    # 3 échecs depuis chacune de deux IP : aucune n'atteint 5, mais 6 au total.
    for ip in ("10.0.0.1", "10.0.0.2"):
        for _ in range(3):
            assert session_store.is_pin_locked(ip, ip) is None
            session_store.register_pin_failure(ip, ip)

    assert session_store.is_pin_locked("10.0.0.3", "x") == session_store.PIN_LOCK_WINDOW_SECONDS


def test_pin_lock_per_ip_still_applies(monkeypatch):
    from app.core import session_store

    monkeypatch.setattr(session_store, "redis_client", FakeSyncRedis())
    for _ in range(session_store.PIN_MAX_ATTEMPTS):
        session_store.register_pin_failure("10.0.0.9", "agent")

    assert session_store.is_pin_locked("10.0.0.9", "x") is not None
    assert session_store.is_pin_locked("10.0.0.10", "x") is None
    # Le compte visé, lui, est bloqué depuis toute adresse.
    assert session_store.is_pin_locked("10.0.0.10", "Agent") is not None


def test_password_locks_after_five_failures(monkeypatch):
    """A03."""
    import pytest
    from fastapi import HTTPException

    from app.core import session_store
    from app.core.config import LOGIN_MAX_FAILURES_PER_USER
    from app.routes import auth

    monkeypatch.setattr(session_store, "redis_client", FakeSyncRedis())
    monkeypatch.setattr(auth, "LOGIN_MAX_FAILURES_PER_USER", 5)
    scopes = auth._login_scopes("10.0.0.1", "Chef")
    for _ in range(5):
        auth._ensure_not_locked(scopes)
        auth._record_failure(scopes)
    with pytest.raises(HTTPException) as refused:
        auth._ensure_not_locked(scopes)
    assert refused.value.status_code == 429
    assert refused.value.detail["retry_after_seconds"] == 900
    # Un collègue derrière la même adresse n'est pas bloqué.
    auth._ensure_not_locked(auth._login_scopes("10.0.0.1", "autre"))
    assert LOGIN_MAX_FAILURES_PER_USER <= 10
