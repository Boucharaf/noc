from datetime import datetime
from types import SimpleNamespace

import pytest

from app.routes import incidents as incidents_routes
from app.routes import kpi as kpi_routes
from app.routes import report as report_routes
from tests.conftest import API_KEY_HEADERS

SUMMARY = {
    "period": {"month": 4, "year": 2026, "label": "Avril 2026"},
    "kpi": {"total_incidents": 32},
    "vs_previous_month": {"incidents_delta": 4},
}


@pytest.fixture(autouse=True)
def no_cache(monkeypatch):
    """Redis is not available in tests; make the cache an explicit no-op."""
    monkeypatch.setattr("app.services.cache_service.get_cached", lambda key: None)
    monkeypatch.setattr("app.services.cache_service.set_cached", lambda key, value, ttl=None: None)
    monkeypatch.setattr("app.services.cache_service.invalidate_prefix", lambda prefix: None)


@pytest.fixture(autouse=True)
def fake_session_store(monkeypatch):
    """app.core.session_store deliberately lets Redis errors propagate (see
    its module docstring) rather than degrading session security silently —
    correct in production, but it means every /api/auth/login|refresh call
    needs a real Redis here. None is available in tests, so replace it with
    an in-memory stand-in that preserves the same jti-rotation semantics the
    routes rely on."""
    store: dict[str, int] = {}

    def _store(user_id, jti, expire_at):
        store[jti] = user_id

    def _valid(jti, user_id):
        return store.get(jti) == user_id

    def _rotate(old_jti, user_id, new_jti, new_expire_at):
        store.pop(old_jti, None)
        store[new_jti] = user_id

    def _revoke_one(jti, user_id):
        store.pop(jti, None)

    def _revoke_all(user_id):
        for jti in [j for j, uid in store.items() if uid == user_id]:
            store.pop(jti, None)

    monkeypatch.setattr("app.routes.auth.session_store.store_refresh_session", _store)
    monkeypatch.setattr("app.routes.auth.session_store.is_refresh_session_valid", _valid)
    monkeypatch.setattr("app.routes.auth.session_store.rotate_refresh_session", _rotate)
    monkeypatch.setattr("app.routes.auth.session_store.revoke_refresh_session", _revoke_one)
    monkeypatch.setattr("app.routes.auth.session_store.revoke_all_sessions", _revoke_all)
    monkeypatch.setattr("app.routes.auth.session_store.is_pin_locked", lambda ip: None)
    monkeypatch.setattr("app.routes.auth.session_store.register_pin_failure", lambda ip: None)
    monkeypatch.setattr("app.routes.auth.session_store.clear_pin_failures", lambda ip: None)


@pytest.fixture
def fake_summary(monkeypatch):
    monkeypatch.setattr(kpi_routes.kpi_service, "get_summary", lambda db, m, y: SUMMARY)


# --- Session renewal ---


def test_refresh_requires_a_valid_token(client):
    """An expired session must not be revivable — renewal runs off the access
    token itself, so once it lapses the only way back in is a fresh login."""
    assert client.post("/api/auth/refresh").status_code == 401


def test_refresh_returns_a_new_token_and_its_lifetime(client, monkeypatch):
    """Le refresh se fait via le cookie httpOnly posé au login, pas via le
    header Authorization (voir la note d'architecture dans
    app/routes/auth.py) — donc on se connecte d'abord pour obtenir ce
    cookie, que TestClient conserve automatiquement pour l'appel suivant."""
    monkeypatch.setattr(
        "app.routes.auth.auth_service.authenticate_with_password",
        lambda db, username, password: SimpleNamespace(
            id=1, username="directeur.test", full_name="Directeur NOC", role="directeur"
        ),
    )
    login_response = client.post(
        "/api/auth/login", json={"username": "directeur.test", "password": "x"}
    )
    assert login_response.status_code == 200
    assert "noc_refresh" in login_response.cookies

    response = client.post("/api/auth/refresh")
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    # The client renews ahead of expiry using this, rather than parsing the JWT.
    assert body["expires_in"] > 0
    assert body["user"]["username"] == "directeur.test"


def test_login_reports_token_lifetime(client, monkeypatch):
    monkeypatch.setattr(
        "app.routes.auth.auth_service.authenticate_with_password",
        lambda db, username, password: SimpleNamespace(
            id=1, username="directeur.test", full_name="Directeur NOC", role="directeur"
        ),
    )
    body = client.post(
        "/api/auth/login", json={"username": "directeur.test", "password": "x"}
    ).json()
    assert body["expires_in"] > 0


# --- Auth on read endpoints (spec §10.1) ---


def test_kpi_summary_requires_auth(client):
    response = client.get("/api/kpi/summary", params={"month": 4, "year": 2026})
    assert response.status_code == 401


def test_kpi_summary_allows_any_role(client, analyst_headers, fake_summary):
    response = client.get(
        "/api/kpi/summary", params={"month": 4, "year": 2026}, headers=analyst_headers
    )
    assert response.status_code == 200
    assert response.json() == SUMMARY


def test_sla_requires_auth(client):
    assert client.get("/api/sla", params={"month": 4, "year": 2026}).status_code == 401


def test_alerts_requires_auth(client):
    assert client.get("/api/alerts/open").status_code == 401


def test_compare_endpoint(client, admin_headers, monkeypatch):
    payload = {"period": SUMMARY["period"], "kpi": SUMMARY["kpi"], "comparisons": []}
    monkeypatch.setattr(kpi_routes.kpi_service, "get_comparison", lambda db, m, y: payload)
    response = client.get(
        "/api/kpi/compare", params={"month": 4, "year": 2026}, headers=admin_headers
    )
    assert response.status_code == 200
    assert response.json() == payload


# --- Report auth: JWT or static API key ---


def test_report_accepts_api_key(client, monkeypatch):
    monkeypatch.setattr(
        report_routes.report_service, "build_report_data", lambda db, m, y: SUMMARY
    )
    response = client.get(
        "/api/report/monthly",
        params={"month": 4, "year": 2026},
        headers=API_KEY_HEADERS,
    )
    assert response.status_code == 200


def test_report_rejects_anonymous(client):
    response = client.get("/api/report/monthly", params={"month": 4, "year": 2026})
    assert response.status_code == 401


# --- RBAC on write actions ---

FAKE_INCIDENT = SimpleNamespace(
    id=4821,
    node_id=12,
    itop_ticket_id=None,
    shift="auto",
    created_at=datetime(2026, 5, 17, 3, 22, 1),
    severity="critical",
    status="open",
    detected_at=datetime(2026, 5, 17, 3, 22, 0),
    description="Perte de connectivité",
)

# incident_service.ingest_incident renvoie (incident, node, created) — le
# node est réutilisé pour le broadcast/la notification sans second aller-
# retour DB (voir la docstring du service) ; fake_ingest doit fournir le
# même tuple à trois éléments.
FAKE_NODE = SimpleNamespace(code="DED-001", name="DREP Dédougou")


@pytest.fixture
def fake_incident_service(monkeypatch):
    monkeypatch.setattr(
        incidents_routes.incident_service,
        "resolve_incident",
        lambda db, incident_id, resolved_at, notes: FAKE_INCIDENT,
    )
    monkeypatch.setattr(
        incidents_routes.incident_service,
        "acknowledge_incident",
        lambda db, incident_id, acknowledged_at: FAKE_INCIDENT,
    )


def test_analyst_cannot_resolve(client, analyst_headers, fake_incident_service):
    response = client.patch(
        "/api/incidents/4821/resolve", json={}, headers=analyst_headers
    )
    assert response.status_code == 403


def test_noc_agent_can_acknowledge(client, noc_agent_headers, fake_incident_service):
    response = client.patch(
        "/api/incidents/4821/acknowledge", json={}, headers=noc_agent_headers
    )
    assert response.status_code == 200


def test_admin_can_resolve(client, admin_headers, fake_incident_service):
    response = client.patch("/api/incidents/4821/resolve", json={}, headers=admin_headers)
    assert response.status_code == 200


# --- Ingest webhook ---

INGEST_PAYLOAD = {
    "external_id": "zabbix-alert-48291",
    "source_tool": "zabbix",
    "node_code": "DED-001",
    "severity": "critical",
    "status": "open",
    "detected_at": "2026-05-17T03:22:00Z",
    "description": "Perte de connectivité",
}


@pytest.fixture
def fake_ingest(monkeypatch):
    published = []
    notified = []
    monkeypatch.setattr(
        incidents_routes.incident_service,
        "ingest_incident",
        lambda db, payload: (FAKE_INCIDENT, FAKE_NODE, True),
    )
    monkeypatch.setattr(
        incidents_routes.alert_broadcaster, "publish_alert", published.append
    )
    monkeypatch.setattr(
        incidents_routes.notification_service,
        "notify_critical_incident",
        lambda *args: notified.append(args),
    )
    return published, notified


def test_ingest_requires_api_key(client, fake_ingest):
    assert client.post("/api/incidents/ingest", json=INGEST_PAYLOAD).status_code == 401


def test_ingest_rejects_jwt_of_dashboard_user(client, admin_headers, fake_ingest):
    response = client.post(
        "/api/incidents/ingest", json=INGEST_PAYLOAD, headers=admin_headers
    )
    assert response.status_code == 401


def test_ingest_creates_broadcasts_and_notifies(client, fake_ingest):
    published, notified = fake_ingest
    response = client.post(
        "/api/incidents/ingest", json=INGEST_PAYLOAD, headers=API_KEY_HEADERS
    )
    assert response.status_code == 201
    assert response.json()["incident_id"] == 4821

    assert len(published) == 1
    assert published[0]["node_code"] == "DED-001"
    assert published[0]["severity"] == "critical"

    # critical severity → SMS/email background task fired
    assert len(notified) == 1
    assert notified[0][1] == "DED-001"


def test_ingest_non_critical_does_not_notify(client, fake_ingest, monkeypatch):
    published, notified = fake_ingest
    medium_incident = SimpleNamespace(**{**FAKE_INCIDENT.__dict__, "severity": "medium"})
    monkeypatch.setattr(
        incidents_routes.incident_service,
        "ingest_incident",
        lambda db, payload: (medium_incident, FAKE_NODE, True),
    )
    payload = {**INGEST_PAYLOAD, "severity": "medium"}
    response = client.post("/api/incidents/ingest", json=payload, headers=API_KEY_HEADERS)
    assert response.status_code == 201
    assert len(published) == 1
    assert notified == []


def test_ingest_duplicate_is_idempotent(client, fake_ingest, monkeypatch):
    """A re-reported still-open alert returns 200 and triggers no side effects."""
    published, notified = fake_ingest
    monkeypatch.setattr(
        incidents_routes.incident_service,
        "ingest_incident",
        lambda db, payload: (FAKE_INCIDENT, FAKE_NODE, False),
    )
    response = client.post(
        "/api/incidents/ingest", json=INGEST_PAYLOAD, headers=API_KEY_HEADERS
    )
    assert response.status_code == 200
    assert response.json()["incident_id"] == FAKE_INCIDENT.id
    assert published == []
    assert notified == []


def test_ingest_validates_source_tool(client, fake_ingest):
    payload = {**INGEST_PAYLOAD, "source_tool": "solarwinds"}
    response = client.post("/api/incidents/ingest", json=payload, headers=API_KEY_HEADERS)
    assert response.status_code == 422


# --- Bulk ingest (batch pollers) ---

BULK_RESULT = {
    "received": 2,
    "created": 2,
    "duplicates": 0,
    "unknown_node": 0,
    "resolved": 0,
}


@pytest.fixture
def fake_bulk_ingest(monkeypatch):
    published = []
    notified = []
    invalidated = []
    monkeypatch.setattr(
        incidents_routes.incident_service,
        "ingest_incidents_bulk",
        lambda db, payloads: {**BULK_RESULT, "received": len(payloads)},
    )
    monkeypatch.setattr(
        incidents_routes.cache_service, "invalidate_prefix", invalidated.append
    )
    monkeypatch.setattr(
        incidents_routes.alert_broadcaster, "publish_alert", published.append
    )
    monkeypatch.setattr(
        incidents_routes.notification_service,
        "notify_critical_incident",
        lambda *args: notified.append(args),
    )
    return published, notified, invalidated


def test_bulk_ingest_requires_api_key(client, fake_bulk_ingest):
    response = client.post(
        "/api/incidents/ingest/bulk", json={"incidents": [INGEST_PAYLOAD]}
    )
    assert response.status_code == 401


def test_bulk_ingest_returns_counts(client, fake_bulk_ingest):
    response = client.post(
        "/api/incidents/ingest/bulk",
        json={"incidents": [INGEST_PAYLOAD, INGEST_PAYLOAD]},
        headers=API_KEY_HEADERS,
    )
    assert response.status_code == 200
    assert response.json() == BULK_RESULT


def test_bulk_ingest_never_notifies_even_on_critical(client, fake_bulk_ingest):
    """A pass reconciling a whole active set must not page the permanence once
    per alarm — that is the entire reason the batch path exists."""
    published, notified, _ = fake_bulk_ingest
    response = client.post(
        "/api/incidents/ingest/bulk",
        json={"incidents": [INGEST_PAYLOAD]},  # severity "critical"
        headers=API_KEY_HEADERS,
    )
    assert response.status_code == 200
    assert published == []
    assert notified == []


def test_bulk_ingest_invalidates_kpi_cache(client, fake_bulk_ingest):
    """Otherwise the dashboard keeps serving the figures cached before the
    batch — a pass that resolved 190 incidents still reporting 0% resolution."""
    _, _, invalidated = fake_bulk_ingest
    client.post(
        "/api/incidents/ingest/bulk",
        json={"incidents": [INGEST_PAYLOAD]},
        headers=API_KEY_HEADERS,
    )
    assert invalidated == ["kpi:"]


def test_bulk_ingest_validates_each_incident(client, fake_bulk_ingest):
    payload = {**INGEST_PAYLOAD, "source_tool": "solarwinds"}
    response = client.post(
        "/api/incidents/ingest/bulk",
        json={"incidents": [INGEST_PAYLOAD, payload]},
        headers=API_KEY_HEADERS,
    )
    assert response.status_code == 422


def test_bulk_ingest_rejects_oversized_batch(client, fake_bulk_ingest):
    response = client.post(
        "/api/incidents/ingest/bulk",
        json={"incidents": [INGEST_PAYLOAD] * 5001},
        headers=API_KEY_HEADERS,
    )
    assert response.status_code == 422
