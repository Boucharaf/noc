"""Modèles ORM.

Séparés en deux fichiers selon qui écrit la table :
  * warehouse.py  — tables créées ET peuplées par l'ETL (lecture seule ici)
  * operations.py — dim_user + tables `ops_*`, propres au backend
"""
from app.models.operations import (
    AuditLog,
    FieldIntervention,
    IncidentAssignment,
    IncidentNotified,
    IncidentTimeline,
    MaintenanceWindow,
    NotificationLog,
    PushSubscription,
    SlaTarget,
    User,
)
from app.models.warehouse import (
    Cause,
    Incident,
    Link,
    Locality,
    MetricValue,
    Ministry,
    Node,
    NodeSourceMap,
    Region,
    SupervisionCoverageDaily,
)

__all__ = [
    # Entrepôt (ETL)
    "Ministry", "Region", "Locality", "Node", "Link", "NodeSourceMap",
    "Cause", "Incident", "SupervisionCoverageDaily", "MetricValue",
    # Backend
    "User", "IncidentTimeline", "IncidentAssignment", "SlaTarget",
    "MaintenanceWindow", "FieldIntervention", "PushSubscription",
    "NotificationLog", "AuditLog", "IncidentNotified",
]
