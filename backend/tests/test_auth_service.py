import pytest
from fastapi import HTTPException

from app.services import auth_service
from tests.conftest import USERS


def test_password_hash_roundtrip():
    hashed = auth_service.hash_password("s3cret!")
    assert hashed != "s3cret!"
    assert auth_service.verify_password("s3cret!", hashed)
    assert not auth_service.verify_password("wrong", hashed)


def test_pin_hash_is_deterministic():
    assert auth_service.hash_pin("1234") == auth_service.hash_pin("1234")
    assert auth_service.hash_pin("1234") != auth_service.hash_pin("4321")


def test_access_token_roundtrip():
    user = USERS[1]
    token = auth_service.create_access_token(user)
    payload = auth_service.decode_access_token(token)
    assert payload["sub"] == "1"
    assert payload["role"] == "directeur"
    assert payload["username"] == "directeur.test"


def test_invalid_token_rejected():
    with pytest.raises(HTTPException) as exc:
        auth_service.decode_access_token("not-a-token")
    assert exc.value.status_code == 401
