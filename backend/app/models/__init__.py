"""
Modèles ORM du NOC.

UN SEUL FICHIER, désormais. L'ancienne séparation entre `warehouse.py`
(tables peuplées par l'ETL, lues ici) et `operations.py` n'a plus lieu
d'être : les tables de l'entrepôt ont disparu avec lui.

L'état courant des équipements et des alertes vit dans l'instantané Redis
(collector/state.py), l'historique chez les outils sources
(backend/app/services/history_service.py). Ne reste ici que ce que le NOC
produit lui-même — voir backend/sql/schema.sql.
"""
from app.models.operations import (
    AlertNotified,
    AuditLog,
    HistAlert,
    HistState,
    KpiDaily,
    NotificationLog,
    NotificationRetry,
    PushSubscription,
    SlaTarget,
    User,
)

__all__ = [
    "AlertNotified",
    "AuditLog",
    "HistAlert",
    "HistState",
    "KpiDaily",
    "NotificationLog",
    "NotificationRetry",
    "PushSubscription",
    "SlaTarget",
    "User",
]
