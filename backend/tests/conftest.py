import os

# Must be set before any app module is imported (constants are read at import time).
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("NOC_API_KEY", "test-api-key")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("SYNC_MV_REFRESH", "false")
os.environ.setdefault("NOTIFICATIONS_ENABLED", "false")
os.environ.setdefault("REDIS_HOST", "127.0.0.1")
# TestClient parle en http://, pas https:// — un cookie Secure ne serait
# jamais renvoyé par le client de test (comportement identique à un vrai
# navigateur), donc désactivé ici uniquement. Ne jamais faire ça en prod.
os.environ.setdefault("REFRESH_COOKIE_SECURE", "false")

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.services.auth_service import create_access_token

API_KEY_HEADERS = {"Authorization": "Bearer test-api-key"}


def make_user(user_id: int, username: str, role: str) -> User:
    return User(
        id=user_id,
        username=username,
        full_name=f"Test {username}",
        role=role,
        password_hash="x",
        is_active=True,
    )


# Rôles à jour avec le modèle v2 (voir app/models/user.py::VALID_ROLES).
# "admin"/"analyst"/"noc_agent" n'existent plus depuis le passage aux 4 rôles
# distincts (directeur, chef_noc, technicien, agent_terrain) ; les anciens
# noms de fixtures sont conservés pour ne pas casser tous les appels de test,
# mais pointent désormais vers un rôle réel.
USERS = {
    1: make_user(1, "directeur.test", "directeur"),
    2: make_user(2, "agent.test", "agent_terrain"),
    3: make_user(3, "technicien.test", "technicien"),
}


class _FakeQuery:
    """Juste assez de l'API Query de SQLAlchemy pour ce que
    get_current_user/require_role appellent réellement :
    db.query(User).filter(User.id == x, User.is_active.is_(True)).first().

    Ne prétend pas être un faux ORM générique : n'importe quel autre usage de
    db.query(...) dans une route testée avec le fixture `client` doit plutôt
    être monkeypatché au niveau du service (voir fake_incident_service dans
    test_api_endpoints.py), pas ajouté ici.
    """

    def __init__(self, model):
        self._model = model
        self._pk = None

    def filter(self, *criteria):
        for c in criteria:
            col = getattr(getattr(c, "left", None), "key", None)
            val = getattr(getattr(c, "right", None), "value", None)
            if col == "id":
                self._pk = val
        return self

    def first(self):
        user = USERS.get(self._pk)
        if user is not None and getattr(user, "is_active", True):
            return user
        return None


class FakeSession:
    """Juste assez d'une Session SQLAlchemy pour get_current_user (db.get et
    la requête filtrée ci-dessus). Toute route qui a besoin de plus (create,
    commit, requêtes métier...) doit monkeypatcher le service concerné plutôt
    que d'étendre ce faux — voir les fixtures fake_* de test_api_endpoints.py.
    """

    def get(self, model, pk):
        return USERS.get(pk)

    def query(self, model):
        return _FakeQuery(model)


@pytest.fixture
def client():
    app.dependency_overrides[get_db] = FakeSession
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def auth_headers(user_id: int) -> dict:
    token = create_access_token(USERS[user_id])
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers():
    """Rôle le plus privilégié — directeur (peut tout faire : refresh,
    compare, resolve)."""
    return auth_headers(1)


@pytest.fixture
def analyst_headers():
    """Rôle sans droit de résolution d'incident — agent_terrain (le seul
    des 4 rôles exclu de _RESOLVE_ROLES, cf. app/routes/incidents.py)."""
    return auth_headers(2)


@pytest.fixture
def noc_agent_headers():
    """Rôle opérationnel pouvant acquitter — technicien."""
    return auth_headers(3)
