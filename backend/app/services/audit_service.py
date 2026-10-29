"""
Journal d'audit — qui a fait quoi, quand, depuis où.

CE QUI EST TRACÉ : ce qui donne ou retire un accès, et ce qui change une
règle de mesure. Connexions (réussies et refusées), comptes créés, modifiés,
désactivés, mots de passe et PIN fixés, sessions coupées, objectifs SLA
modifiés. Les lectures ne le sont pas : elles n'engagent personne et
noieraient le journal.

JAMAIS DE SECRET dans `detail` : ni mot de passe, ni PIN, ni jeton. On note
qu'un mot de passe a été changé, pas lequel.

UNE ÉCRITURE QUI ÉCHOUE NE DÉFAIT PAS L'ACTION. L'action est déjà validée en
base quand on la trace (les services valident eux-mêmes) ; refuser après
coup la réponse à l'utilisateur ne l'annulerait pas. L'échec est journalisé
en erreur pour être vu par l'exploitation.
"""
from __future__ import annotations

import logging

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.rate_limit import client_ip
from app.models import AuditLog, User

logger = logging.getLogger(__name__)

# Libellés des actions, repris tels quels par l'interface.
ACTIONS = {
    "auth.login": "Connexion",
    "auth.login_failed": "Connexion refusée",
    "auth.pin_login": "Connexion par PIN",
    "auth.pin_login_failed": "Connexion par PIN refusée",
    "auth.password_changed": "Mot de passe changé",
    "auth.profile_updated": "Profil modifié",
    "auth.sessions_revoked": "Sessions coupées",
    "user.created": "Compte créé",
    "user.updated": "Compte modifié",
    "user.deactivated": "Compte désactivé",
    "user.password_reset": "Mot de passe réinitialisé",
    "user.pin_reset": "PIN réinitialisé",
    "sla.target_updated": "Objectif SLA modifié",
}


def record(
    db: Session,
    action: str,
    *,
    actor: User | None = None,
    target: str | None = None,
    detail: dict | None = None,
    request: Request | None = None,
) -> None:
    """Ajoute une ligne au journal et la valide aussitôt."""
    if action not in ACTIONS:
        raise ValueError(f"Action d'audit inconnue : {action}")
    try:
        db.add(
            AuditLog(
                user_id=actor.id if actor is not None else None,
                action=action,
                target=target,
                detail=detail or None,
                ip_address=client_ip(request) if request is not None else None,
            )
        )
        db.commit()
    except Exception:  # noqa: BLE001 — voir l'en-tête du module.
        db.rollback()
        logger.exception("Journal d'audit : écriture impossible (%s, %s)", action, target)


def list_entries(
    db: Session,
    action: str | None = None,
    user_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """Entrées du plus récent au plus ancien, avec le nom de leur auteur."""
    conditions = []
    if action:
        conditions.append(AuditLog.action == action)
    if user_id is not None:
        conditions.append(AuditLog.user_id == user_id)

    total = db.execute(select(func.count()).select_from(AuditLog).where(*conditions)).scalar()
    rows = db.execute(
        select(AuditLog, User.username, User.full_name)
        .outerjoin(User, User.id == AuditLog.user_id)
        .where(*conditions)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return {
        "entries": [
            {
                "id": entry.id,
                "at": entry.created_at.isoformat() if entry.created_at else None,
                "action": entry.action,
                "label": ACTIONS.get(entry.action, entry.action),
                "user_id": entry.user_id,
                "user": full_name or username,
                "target": entry.target,
                "detail": entry.detail or {},
                "ip": entry.ip_address,
            }
            for entry, username, full_name in rows
        ],
        "total": int(total or 0),
        "limit": limit,
        "offset": offset,
        "actions": [{"value": key, "label": label} for key, label in ACTIONS.items()],
    }
