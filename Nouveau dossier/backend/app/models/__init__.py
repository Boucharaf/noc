"""
Modèles ORM du NOC.

L'état courant des équipements et des alertes vit dans l'instantané Redis
(collector/state.py), l'historique chez les outils sources
(backend/app/services/history_service.py). Ne reste ici que ce que le NOC
produit lui-même — voir backend/sql/schema.sql.
"""
from app.models.operations import (
    AlertNotified,
    AlertState,
    AlertTimeline,
    AuditLog,
    FieldIntervention,
    KpiDaily,
    MaintenanceWindow,
    ManualIncident,
    NotificationLog,
    PushSubscription,
    SlaTarget,
    User,
)

__all__ = [
    "AlertNotified",
    "AlertState",
    "AlertTimeline",
    "AuditLog",
    "FieldIntervention",
    "KpiDaily",
    "MaintenanceWindow",
    "ManualIncident",
    "NotificationLog",
    "PushSubscription",
    "SlaTarget",
    "User",
]
