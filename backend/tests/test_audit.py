"""Journal d'audit : écriture, robustesse, branchement sur les actions sensibles."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.models import AuditLog
from app.routes import auth as auth_routes
from app.routes import users as users_routes
from app.services import audit_service


class _Session:
    def __init__(self, fail=False):
        self.rows = []
        self.fail = fail
        self.rolled_back = False

    def add(self, row):
        self.rows.append(row)

    def commit(self):
        if self.fail:
            raise RuntimeError("database down")

    def rollback(self):
        self.rolled_back = True

    def get(self, _model, _key):
        return None


def _request(ip="198.51.100.20"):
    return Request(
        {
            "type": "http", "http_version": "1.1", "method": "POST", "scheme": "http",
            "path": "/", "raw_path": b"/", "query_string": b"", "headers": [],
            "client": (ip, 1234), "server": ("backend", 8000),
        }
    )


def test_record_writes_actor_target_detail_and_ip():
    db = _Session()
    actor = SimpleNamespace(id=7)

    audit_service.record(
        db, "user.created", actor=actor, target="a.traore",
        detail={"role": "technicien"}, request=_request(),
    )

    (row,) = db.rows
    assert isinstance(row, AuditLog)
    assert (row.user_id, row.action, row.target) == (7, "user.created", "a.traore")
    assert row.detail == {"role": "technicien"}
    assert row.ip_address == "198.51.100.20"


def test_failed_audit_write_does_not_break_the_action():
    db = _Session(fail=True)

    audit_service.record(db, "auth.login", target="a.traore")

    assert db.rolled_back is True


def test_unknown_action_is_a_programming_error():
    with pytest.raises(ValueError):
        audit_service.record(_Session(), "user.deleted")


def test_account_creation_is_audited_without_secrets(monkeypatch):
    recorded = []
    monkeypatch.setattr(
        users_routes.user_service,
        "create_user",
        lambda _db, payload: {"id": 12, "username": payload["username"], "role": payload["role"]},
    )
    monkeypatch.setattr(
        audit_service, "record", lambda _db, action, **kwargs: recorded.append((action, kwargs))
    )
    payload = users_routes.UserCreate(
        username="a.traore", full_name="A. Traoré", role="technicien",
        password="Un-mot-de-passe-solide-42",
    )

    users_routes.create_user(payload, _request(), db=None, admin=SimpleNamespace(id=1))

    ((action, kwargs),) = recorded
    assert action == "user.created"
    assert kwargs["target"] == "a.traore"
    assert kwargs["detail"] == {"user_id": 12, "role": "technicien"}
    assert "Un-mot-de-passe-solide-42" not in repr(kwargs)


def test_refused_login_is_audited_with_the_attempted_username_only(monkeypatch):
    recorded = []

    def refuse(_db, _username, _password):
        raise HTTPException(401, "Identifiants invalides.")

    monkeypatch.setattr(auth_routes.auth_service, "authenticate_with_password", refuse)
    monkeypatch.setattr(auth_routes, "_ensure_not_locked", lambda _scopes: None)
    monkeypatch.setattr(auth_routes, "_record_failure", lambda _scopes: None)
    monkeypatch.setattr(
        audit_service, "record", lambda _db, action, **kwargs: recorded.append((action, kwargs))
    )
    payload = auth_routes.LoginPayload(username="intrus", password="devine-moi-123")

    with pytest.raises(HTTPException):
        auth_routes.login(payload, _request(), response=None, db=None)

    ((action, kwargs),) = recorded
    assert action == "auth.login_failed"
    assert kwargs["target"] == "intrus"
    assert "devine-moi-123" not in repr(kwargs)
