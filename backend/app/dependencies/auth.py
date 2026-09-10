"""Dépendances FastAPI d'authentification et d'autorisation.

C'est ici que vit le vrai contrôle d'accès. Le RBAC du frontend
(frontend/src/api/permissions.js) n'est que du confort d'interface :
sans ces dépendances appliquées à chaque route sensible, un rôle à
faibles privilèges pourrait appeler ces routes directement en HTTP.
"""
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import INTERNAL_API_KEY
from app.db.session import get_db
from app.models import User
from app.services.auth_service import decode_access_token

bearer_scheme = HTTPBearer(auto_error=True)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    payload = decode_access_token(credentials.credentials)

    user = (
        db.query(User)
        .filter(User.id == int(payload["sub"]), User.is_active.is_(True))
        .first()
    )
    if not user:
        raise HTTPException(status_code=401, detail="Compte introuvable ou désactivé.")

    # Le rôle vient toujours de la ligne en base, jamais du seul JWT : si
    # un compte est rétrogradé en cours de session, son jeton d'accès
    # encore valide ne doit pas continuer à porter l'ancien rôle.
    if payload.get("role") != user.role:
        raise HTTPException(status_code=401, detail="Rôle modifié, reconnexion nécessaire.")

    return user


def require_role(*allowed_roles: str):
    """Usage : Depends(require_role("directeur", "chef_noc"))"""

    def _check(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Le rôle « {current_user.role} » n'a pas accès à cette action.",
            )
        return current_user

    return _check


def require_internal_key(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> None:
    """Garde des routes /api/internal/*, appelées par l'ETL.

    Ces routes ne sont jamais appelées par un utilisateur connecté : la
    référence est la clé statique INTERNAL_API_KEY, pas un JWT. Sans clé
    configurée, la route répond 503 plutôt que de s'ouvrir.
    """
    if not INTERNAL_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Intégration interne non configurée (INTERNAL_API_KEY absente).",
        )
    if credentials.credentials != INTERNAL_API_KEY:
        raise HTTPException(status_code=401, detail="Clé interne invalide.")
