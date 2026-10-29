"""Sonde /api/health : ce que la supervision du NOC (Zabbix) peut y lire."""
import asyncio

from starlette.responses import Response

from app.routes import health as health_route
from app.services import notification_service


class _Db:
    def execute(self, statement):
        class _Result:
            def scalar(self):
                return 3

        return _Result()


def _probe(monkeypatch, *, meta, notifications=True, retry=None):
    monkeypatch.setattr(health_route.redis_sync, "ping", lambda: True)

    async def age():
        return 42

    async def get_meta():
        if meta is None:
            raise health_route.live_service.SnapshotUnavailable()
        return meta

    monkeypatch.setattr(health_route.live_service, "snapshot_age_s", age)
    monkeypatch.setattr(health_route.live_service, "get_meta", get_meta)
    monkeypatch.setattr(health_route, "NOTIFICATIONS_ENABLED", notifications)
    monkeypatch.setattr(
        notification_service, "retry_status",
        lambda: retry or {"pending": 0, "abandoned_24h": 0},
    )
    response = Response()
    body = asyncio.run(health_route.health(response, _Db()))
    return response.status_code, body


def test_failed_source_and_abandoned_notification_degrade_without_503(monkeypatch):
    status, body = _probe(
        monkeypatch,
        meta={"tools_ok": ["zabbix", "itop"], "tools_failed": ["netxms"]},
        retry={"pending": 2, "abandoned_24h": 1},
    )
    assert status == 200  # dégradé, pas en panne : le NOC reste utilisable
    assert body["status"] == "degraded"
    assert body["checks"]["sources"] == {
        "status": "degraded", "ok": 2, "failed": 1, "failed_tools": ["netxms"],
    }
    assert body["checks"]["notifications"] == {
        "status": "degraded", "pending": 2, "abandoned_24h": 1,
    }


def test_healthy_noc_and_disabled_notifications(monkeypatch):
    status, body = _probe(
        monkeypatch, meta={"tools_ok": ["zabbix"], "tools_failed": []}, notifications=False
    )
    assert (status, body["status"]) == (200, "ok")
    assert body["checks"]["notifications"] == {"status": "disabled"}
    # Route publique : jamais de message d'erreur d'outil dans la réponse.
    assert "error" not in str(body["checks"]["sources"])
