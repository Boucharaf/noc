"""PIN lié à un poste reconnu (INC-43).

Le PIN n'est accepté que sur un navigateur où un mot de passe a déjà été
saisi avec succès : cookie « noc_device » signé, posé à la connexion par mot
de passe, vérifié AVANT le PIN.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import session_store
from app.db.session import get_db
from app.models import User
from app.routes import auth as auth_routes
from app.services import audit_service, auth_service


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setattr(auth_service, "JWT_SECRET", "s" * 48)


def test_device_token_is_signed_and_expires():
    token = auth_service.create_device_token(now=1_000_000)
    assert auth_service.is_known_device(token, 180, now=1_000_000 + 86400)
    # Trop ancien.
    assert not auth_service.is_known_device(token, 180, now=1_000_000 + 181 * 86400)
    # Falsifié : date prolongée ou signature changée.
    device_id, _issued, signature = token.split(".")
    assert not auth_service.is_known_device(f"{device_id}.2000000.{signature}", 180, now=2_000_000)
    assert not auth_service.is_known_device(f"{device_id}.1000000.{'0' * 64}", 180, now=1_000_001)
    assert not auth_service.is_known_device(None, 180)
    assert not auth_service.is_known_device("n'importe-quoi", 180)


@pytest.fixture
def client(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    User.__table__.create(engine)
    db = sessionmaker(bind=engine)()
    db.add_all([
        User(id=1, username="chef", role="chef_noc", is_active=True,
             password_hash=auth_service.hash_password("mot-de-passe-solide")),
        User(id=2, username="agent", role="agent_terrain", is_active=True,
             pin_hash=auth_service.hash_pin("482913")),
    ])
    db.commit()

    # Redis, sessions et journal : hors sujet ici.
    for name in ("register_failure", "clear_failures", "register_pin_failure",
                 "clear_pin_failures", "store_refresh_session"):
        monkeypatch.setattr(session_store, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(session_store, "lock_ttl", lambda *args: None)
    monkeypatch.setattr(session_store, "is_pin_locked", lambda *args: None)
    monkeypatch.setattr(session_store, "revoke_all_sessions", lambda *args: None)
    monkeypatch.setattr(session_store, "is_access_token_revoked", lambda *args: False)
    monkeypatch.setattr(audit_service, "record", lambda *args, **kwargs: None)
    # Cookies « Secure » : le client de test parle en http.
    monkeypatch.setattr(auth_routes, "REFRESH_COOKIE_SECURE", False)
    monkeypatch.setattr(auth_routes, "PIN_REQUIRE_KNOWN_DEVICE", True)

    app = FastAPI()
    app.include_router(auth_routes.router)
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    db.close()


def test_pin_refused_on_unknown_browser_then_accepted_after_a_password_login(client):
    refused = client.post("/api/auth/pin-login", json={"username": "agent", "pin": "482913"})
    assert refused.status_code == 403
    assert refused.json()["detail"]["error"] == "unknown_device"

    login = client.post(
        "/api/auth/login", json={"username": "chef", "password": "mot-de-passe-solide"}
    )
    assert login.status_code == 200
    assert auth_service.DEVICE_COOKIE_NAME in login.cookies

    # Même navigateur : le PIN de l'agent est accepté (relève sur la console).
    accepted = client.post("/api/auth/pin-login", json={"username": "agent", "pin": "482913"})
    assert accepted.status_code == 200
    assert accepted.json()["user"]["username"] == "agent"


def test_forged_device_cookie_is_refused(client):
    client.cookies.set(auth_service.DEVICE_COOKIE_NAME, "abc.123.def", path="/api/auth")
    assert client.post("/api/auth/pin-login", json={"username": "agent", "pin": "482913"}).status_code == 403


def _known(client):
    client.post("/api/auth/login", json={"username": "chef", "password": "mot-de-passe-solide"})


def test_pin_is_tied_to_the_named_account(client):
    """A02 : un code juste n'ouvre que le compte désigné."""
    _known(client)
    for username in ("chef", "inconnu", ""):
        response = client.post(
            "/api/auth/pin-login", json={"username": username, "pin": "482913"}
        )
        assert response.status_code in (401, 422)
    assert client.post("/api/auth/pin-login", json={"pin": "482913"}).status_code == 422


def test_provisional_password_opens_nothing_but_its_change(client):
    """A01 : compte créé ou réinitialisé par un tiers."""
    from app.routes import users as users_routes

    client.app.include_router(users_routes.router)
    db = client.app.dependency_overrides[get_db]()
    db.get(User, 1).must_change_password = True
    db.commit()
    body = client.post(
        "/api/auth/login", json={"username": "chef", "password": "mot-de-passe-solide"}
    ).json()
    assert body["user"]["must_change_password"] is True
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    refused = client.get("/api/users", headers=headers)
    assert refused.status_code == 403
    assert refused.json()["detail"]["error"] == "password_change_required"
    assert client.patch("/api/auth/me", headers=headers, json={}).status_code == 403
    assert client.get("/api/auth/me", headers=headers).status_code == 200

    def change(new):
        return client.patch("/api/auth/me/password", headers=headers, json={
            "current_password": "mot-de-passe-solide", "new_password": new,
        }).status_code

    assert change("mot-de-passe-solide") == 422
    assert change("un-autre-mot-de-passe") == 204
    assert client.get("/api/users", headers=headers).status_code == 200
    # Réinitialisé par un tiers : de nouveau provisoire.
    auth_service.set_password(db, 1, "provisoire-choisi", provisional=True)
    assert client.get("/api/users", headers=headers).status_code == 403


@pytest.mark.parametrize("phone, ok", [
    ("+226 70 12 34 56", True), ("70123456", True), ("", True), (None, True),
    ("abc70123456", False), ("70-12", False), ("70123456;drop", False), ("+" + "1" * 20, False),
])
def test_phone_format(phone, ok):
    """A16."""
    from app.schemas.users import UserSelfUpdate

    if ok:
        assert UserSelfUpdate(phone_number=phone).phone_number == (phone or None)
    else:
        with pytest.raises(ValueError):
            UserSelfUpdate(phone_number=phone)


def test_pdf_text_has_no_question_mark():
    """A09 : repli hors de l'image."""
    from fpdf import FPDF

    from app.services import pdf_font, report_service

    _family, text = pdf_font.setup(FPDF())
    assert "?" not in text("Écart — 98,5 % → ≤ 4 h · l’œuvre…")
    assert report_service._fmt(98.5, " %") == "98,50 %"
