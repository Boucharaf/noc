"""Compatibilité de sécurité pour les modules legacy encore présents.

Les routes et services actifs du projet utilisent désormais
app.dependencies.auth et app.services.auth_service. Ce module expose les
fonctions attendues par le code héritage afin d'éviter les imports cassés.
"""

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.constants import NOC_API_KEY
from app.db.session import get_db
from app.dependencies.auth import get_current_user as _get_current_user
from app.dependencies.auth import require_role as _require_role

bearer_scheme = HTTPBearer(auto_error=True)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    """Compatibility wrapper for legacy imports."""
    return _get_current_user(credentials=credentials, db=db)


def require_role(*allowed_roles: str):
    """Compatibility wrapper for legacy imports."""
    return _require_role(*allowed_roles)


def verify_secret(raw: str, hashed: str) -> bool:
    """Legacy alias kept for older code paths."""
    from app.services.auth_service import verify_password

    return verify_password(raw, hashed)


def hash_secret(raw: str) -> str:
    """Legacy alias kept for older code paths."""
    from app.services.auth_service import hash_password

    return hash_password(raw)


def decode_token(token: str, expected_type: str) -> dict:
    """Legacy alias kept for older code paths."""
    from app.services.auth_service import decode_access_token

    payload = decode_access_token(token)
    if payload.get("type") != expected_type:
        raise HTTPException(status_code=401, detail="Type de token invalide.")
    return payload


def verify_api_key(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> None:
    """Gate for the ETL/webhook ingest endpoints (POST /api/incidents/ingest[/bulk]).

    These are called by the supervision-tool collectors and Centreon
    webhooks, never by a logged-in dashboard user — so the credential is the
    single static NOC_API_KEY (see app/core/constants.py), not a JWT. A JWT
    presented here simply won't match the string comparison below and is
    correctly rejected with 401, same as a missing/wrong key.
    """
    if not NOC_API_KEY or credentials.credentials != NOC_API_KEY:
        raise HTTPException(status_code=401, detail="Clé API invalide.")


def require_role_or_api_key(*allowed_roles: str):
    """Usage: Depends(require_role_or_api_key("directeur", "chef_noc"))

    Accepts either the static NOC_API_KEY (the ETL beat container downloading
    the scheduled monthly report) or a dashboard user's JWT whose role is in
    allowed_roles. Whichever the Authorization header actually carries is
    tried first as the API key (cheap string comparison); only when that
    fails is it decoded as a JWT, so a malformed/expired JWT from the ETL
    side never masks a legitimate api-key failure behind a decode error.
    """

    def _check(
        credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
        db: Session = Depends(get_db),
    ):
        if NOC_API_KEY and credentials.credentials == NOC_API_KEY:
            return None
        user = _get_current_user(credentials=credentials, db=db)
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Le rôle '{user.role}' n'a pas accès à cette action.",
            )
        return user

    return _check
