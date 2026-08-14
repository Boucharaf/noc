from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.constants import NOC_API_KEY
from app.db.session import get_db
from app.models.user import User
from app.services.auth_service import decode_access_token


def verify_api_key(authorization: str = Header(default="")) -> None:
    """Static bearer key required on supervision-tool webhooks (Centreon/Zabbix -> /ingest).

    Deliberately a shared static key rather than per-caller credentials: the
    callers are monitoring daemons configured by hand, with no way to refresh
    a token and no user behind them to re-authenticate. The trade-off is that
    the key never expires, so it must be treated as a secret with a rotation
    story of its own — changing it means editing every webhook definition.
    """
    expected = f"Bearer {NOC_API_KEY}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def get_current_user(
    authorization: str = Header(default=""), db: Session = Depends(get_db)
) -> User:
    """JWT-bearer auth for dashboard-driven actions (e.g. acknowledge/resolve)."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.removeprefix("Bearer ")
    payload = decode_access_token(token)
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_role(*roles: str):
    """Restrict an endpoint to the given roles.

    The three roles and what they may do: admin reads and writes, analyst
    reads only, noc_agent reads and acknowledges. Enforcement lives here, on
    the server; the frontend hides actions a role cannot perform, but that is
    a courtesy to the user and never the control.
    """

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=403,
                detail=f"Role '{current_user.role}' is not allowed for this action",
            )
        return current_user

    return dependency


def verify_user_or_api_key(
    authorization: str = Header(default=""), db: Session = Depends(get_db)
) -> None:
    """Accept either a dashboard JWT or the static NOC API key.

    Used on /api/report/monthly so the scheduled ETL export (which only holds
    the webhook API key) can pull the end-of-month report."""
    if authorization == f"Bearer {NOC_API_KEY}":
        return
    get_current_user(authorization, db)
