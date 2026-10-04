import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core import rate_limit


class FakeRedis:
    def __init__(self):
        self.counts = {}
        self.expirations = {}

    def incr(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def expire(self, key, seconds):
        self.expirations[key] = seconds
        return True


def _enable_fake_redis(monkeypatch):
    monkeypatch.setattr(rate_limit, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(rate_limit, "redis_client", FakeRedis())


def test_rate_limit_tracks_ip_and_user_separately(monkeypatch):
    _enable_fake_redis(monkeypatch)

    rate_limit.enforce_rate_limit("read", 1, "ip", "192.0.2.10")
    rate_limit.enforce_rate_limit("read", 1, "user", "17")
    rate_limit.enforce_rate_limit("read", 1, "user", "18")

    with pytest.raises(HTTPException) as ip_error:
        rate_limit.enforce_rate_limit("read", 1, "ip", "192.0.2.10")
    with pytest.raises(HTTPException) as user_error:
        rate_limit.enforce_rate_limit("read", 1, "user", "17")

    assert ip_error.value.status_code == 429
    assert user_error.value.status_code == 429


def test_http_middleware_limits_each_ip(monkeypatch):
    _enable_fake_redis(monkeypatch)
    monkeypatch.setattr(rate_limit, "RATE_LIMIT_READ_PER_MIN", 1)
    app = FastAPI()
    app.middleware("http")(rate_limit.rate_limit_middleware)

    @app.get("/api/items")
    def get_items():
        return {"items": []}

    client = TestClient(app)
    headers = {"X-Real-IP": "192.0.2.10"}
    assert client.get("/api/items", headers=headers).status_code == 200
    assert client.get("/api/items", headers=headers).status_code == 429
    assert client.get("/api/items", headers={"X-Real-IP": "192.0.2.11"}).status_code == 200