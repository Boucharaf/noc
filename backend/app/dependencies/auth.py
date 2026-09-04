from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db.session import get_db  # ajuster si le nom réel diffère
from app.models.user import User
from app.services.auth_service import decode_access_token

bearer_scheme = HTTPBearer(auto_error=True)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    payload = decode_access_token(credentials.credentials)  # lève déjà 401 si invalide/expiré

    user = db.query(User).filter(User.id == int(payload["sub"]), User.is_active.is_(True)).first()
    if not user:
        raise HTTPException(status_code=401, detail="Compte introuvable ou désactivé.")

    # Le rôle vient toujours de la ligne DB actuelle, jamais du seul JWT :
    # si un Directeur rétrograde un compte en cours de session, l'ancien
    # access token (valide jusqu'à JWT_EXPIRATION_MINUTES) ne doit pas
    # continuer à porter l'ancien rôle une fois relu ici.
    if payload.get("role") != user.role:
        raise HTTPException(status_code=401, detail="Rôle modifié, reconnexion nécessaire.")

    return user


def require_role(*allowed_roles: str):
    """Usage: Depends(require_role("directeur", "chef_noc"))

    C'est ici, pas dans le frontend, que vit le vrai contrôle d'accès. Le
    RBAC côté client (permissions.js) n'est que du confort d'UI ; sans cette
    dépendance appliquée à chaque route sensible (resolve incident,
    téléchargement de rapport, gestion des utilisateurs...), un rôle à
    faibles privilèges pourrait appeler ces routes directement en HTTP.
    """

    def _check(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Le rôle '{current_user.role}' n'a pas accès à cette action.",
            )
        return current_user

    return _check