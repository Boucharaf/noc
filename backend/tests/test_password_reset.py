"""Réinitialisation du mot de passe par courriel (INC-45).

Ce qui doit tenir :
  * le jeton n'est stocké qu'en empreinte, sert une seule fois, et une
    nouvelle demande annule la précédente ;
  * la demande répond la MÊME chose que le compte existe ou non ;
  * la confirmation change le mot de passe et coupe toutes les sessions ;
  * un jeton faux ou déjà utilisé est refusé.
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
from app.services import audit_service, auth_service, notification_service


class FakeRedis:
    """Le sous-ensemble de Redis utilisé par session_store pour ces routes."""

    def __init__(self):
        self.values, self.ttls = {}, {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, ex=None):
        self.values[key] = value
        self.ttls[key] = ex

    def getdel(self, key):
        self.ttls.pop(key, None)
        return self.values.pop(key, None)

    def delete(self, key):
        self.values.pop(key, None)
        self.ttls.pop(key, None)

    def incr(self, key):
        self.values[key] = int(self.values.get(key, 0)) + 1
        return self.values[key]

    def expire(self, key, seconds):
        self.ttls[key] = seconds

    def ttl(self, key):
        return self.ttls.get(key, -2) if key in self.values else -2


@pytest.fixture
def redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(session_store, "redis_client", fake)
    return fake


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    User.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    session.add_all([
        User(id=1, username="awa", full_name="Awa O.", email="awa@anptic.bf",
             role="chef_noc", password_hash=auth_service.hash_password("ancien-mot-de-passe"),
             is_active=True),
        User(id=2, username="sans.mail", role="technicien", is_active=True,
             password_hash=auth_service.hash_password("ancien-mot-de-passe")),
    ])
    session.commit()
    yield session
    session.close()


@pytest.fixture
def client(db, redis, monkeypatch):
    sent = []
    monkeypatch.setattr(
        notification_service, "send_password_reset_email",
        lambda address, name, link, minutes: sent.append((address, link)) or True,
    )
    revoked = []
    monkeypatch.setattr(session_store, "revoke_all_sessions", revoked.append)
    # Journal d'audit capturé (sa table utilise JSONB, propre à PostgreSQL).
    audited = []
    monkeypatch.setattr(
        audit_service, "record", lambda _db, action, **kwargs: audited.append(action)
    )
    app = FastAPI()
    app.include_router(auth_routes.router)
    app.dependency_overrides[get_db] = lambda: db
    test_client = TestClient(app)
    test_client.sent, test_client.revoked, test_client.audited = sent, revoked, audited
    return test_client


def test_token_is_single_use_and_replaced_by_a_new_request(redis):
    first = session_store.store_password_reset(7)
    second = session_store.store_password_reset(7)

    # Jamais en clair dans Redis.
    assert not any(first in str(key) or first == value for key, value in redis.values.items())
    # La nouvelle demande annule la précédente.
    assert session_store.consume_password_reset(first) is None
    assert session_store.consume_password_reset(second) == 7
    # Usage unique.
    assert session_store.consume_password_reset(second) is None


def test_request_answers_the_same_whether_the_account_exists_or_not(client):
    known = client.post("/api/auth/password-reset/request", json={"identifier": "AWA@anptic.bf"})
    unknown = client.post("/api/auth/password-reset/request", json={"identifier": "personne"})
    no_mail = client.post("/api/auth/password-reset/request", json={"identifier": "sans.mail"})

    assert known.status_code == unknown.status_code == no_mail.status_code == 202
    assert known.json() == unknown.json() == no_mail.json()
    # Un seul courriel, au seul compte qui a une adresse.
    assert [address for address, _link in client.sent] == ["awa@anptic.bf"]
    assert "/reinitialiser#jeton=" in client.sent[0][1]


def test_confirm_sets_password_revokes_sessions_and_burns_the_token(client, db):
    client.post("/api/auth/password-reset/request", json={"identifier": "awa"})
    token = client.sent[0][1].split("jeton=")[1]

    done = client.post(
        "/api/auth/password-reset/confirm",
        json={"token": token, "new_password": "un-nouveau-mot-de-passe"},
    )
    assert done.status_code == 204
    db.expire_all()
    user = db.get(User, 1)
    assert auth_service.verify_password("un-nouveau-mot-de-passe", user.password_hash)
    assert client.revoked == [1]
    assert client.audited == ["auth.password_reset_requested", "auth.password_reset_completed"]

    again = client.post(
        "/api/auth/password-reset/confirm",
        json={"token": token, "new_password": "encore-un-autre-mot"},
    )
    assert again.status_code == 400


def test_confirm_rejects_forged_token_and_short_password(client):
    forged = client.post(
        "/api/auth/password-reset/confirm",
        json={"token": "x" * 43, "new_password": "un-nouveau-mot-de-passe"},
    )
    assert forged.status_code == 400

    client.post("/api/auth/password-reset/request", json={"identifier": "awa"})
    token = client.sent[0][1].split("jeton=")[1]
    short = client.post(
        "/api/auth/password-reset/confirm", json={"token": token, "new_password": "court"}
    )
    assert short.status_code == 422


def test_reset_lifts_the_login_lock(client):
    for _ in range(5):
        last = client.post("/api/auth/login", json={"username": "awa", "password": "faux"})
    # La tentative qui verrouille annonce la durée.
    assert last.status_code == 429
    assert last.json()["detail"]["retry_after_seconds"] > 0
    status = client.post("/api/auth/lock-status", json={"username": "awa"})
    assert status.json()["retry_after_seconds"] > 0
    other = client.post("/api/auth/lock-status", json={"username": "autre"})
    assert other.json()["retry_after_seconds"] == 0

    client.post("/api/auth/password-reset/request", json={"identifier": "awa"})
    token = client.sent[0][1].split("jeton=")[1]
    client.post(
        "/api/auth/password-reset/confirm",
        json={"token": token, "new_password": "un-nouveau-mot-de-passe"},
    )
    status = client.post("/api/auth/lock-status", json={"username": "awa"})
    assert status.json()["retry_after_seconds"] == 0


def test_pin_only_account_cannot_gain_a_password(client, db):
    db.add(User(id=3, username="terrain", email="t@anptic.bf", role="agent_terrain",
                is_active=True))
    db.commit()
    answer = client.post("/api/auth/password-reset/request", json={"identifier": "terrain"})
    assert answer.status_code == 202
    assert client.sent == []


def test_requests_are_limited_per_account(client):
    codes = [
        client.post("/api/auth/password-reset/request", json={"identifier": "awa"}).status_code
        for _ in range(5)
    ]
    assert codes[:3] == [202, 202, 202]
    assert codes[3:] == [429, 429]
