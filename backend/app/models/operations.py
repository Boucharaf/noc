"""
Nouvelles tables métier qui n'existaient pas dans la v1 et qui deviennent
nécessaires dès qu'on distingue 4 rôles avec des besoins réels différents :

- FieldIntervention : le cœur du métier de l'Agent Terrain. Sans ça, son
  rôle dans la base se limite à "peut se connecter" — aucune valeur.
- EscalationRule : formalise ce qui aujourd'hui se passe "à la voix"
  (un incident critique non traité en X minutes remonte au Chef NOC,
  puis au Directeur). Rend l'escalade automatisable par Celery.
- NotificationLog : trace ce qui a été envoyé à qui, sur quel canal —
  utile pour debug push/SMS et pour prouver qu'une alerte a bien été
  notifiée (audit SLA).
"""

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base


class FieldIntervention(Base):
    __tablename__ = "fact_field_intervention"

    id = Column(BigInteger, primary_key=True)
    incident_id = Column(BigInteger, ForeignKey("fact_incident.id"))  # nullable: tournée de routine
    node_id = Column(Integer, ForeignKey("dim_node.id"), nullable=False)
    agent_user_id = Column(Integer, ForeignKey("dim_user.id"), nullable=False)

    status = Column(String(20), nullable=False, default="scheduled")  # scheduled|en_route|on_site|done|cancelled
    scheduled_at = Column(DateTime)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)

    # géolocalisation du check-in, pour confirmer une présence réelle sur site
    checkin_latitude = Column(Numeric(9, 6))
    checkin_longitude = Column(Numeric(9, 6))

    report_text = Column(Text)
    photo_urls = Column(Text)  # JSON-encodé, liste d'URLs (S3/local storage)

    created_at = Column(DateTime, server_default=func.now())

    incident = relationship("Incident")
    node = relationship("Node")
    agent = relationship("User")


class EscalationRule(Base):
    """Règle déclenchée par le scheduler Celery existant : si un incident
    de sévérité X n'est pas acquitté/résolu après N minutes, il est
    escaladé automatiquement (incident.escalation_level += 1,
    notification au rôle cible, ligne dans fact_incident_timeline).
    """

    __tablename__ = "dim_escalation_rule"

    id = Column(Integer, primary_key=True)
    severity = Column(String(20), nullable=False)
    trigger_after_minutes = Column(Integer, nullable=False)
    from_escalation_level = Column(Integer, nullable=False)  # niveau actuel
    escalate_to_role = Column(String(20), nullable=False)  # chef_noc|directeur
    is_active = Column(Integer, default=1)


class NotificationLog(Base):
    __tablename__ = "fact_notification_log"

    id = Column(BigInteger, primary_key=True)
    user_id = Column(Integer, ForeignKey("dim_user.id"), nullable=False)
    incident_id = Column(BigInteger, ForeignKey("fact_incident.id"))
    channel = Column(String(20), nullable=False)  # push|sms|email
    status = Column(String(20), nullable=False, default="sent")  # sent|failed|read
    sent_at = Column(DateTime, server_default=func.now())

    user = relationship("User")
    incident = relationship("Incident")


class AuditLog(Base):
    """Journal transverse (au-delà des incidents) : connexions, création/
    modification d'un nœud, changement de rôle, export de rapport... Requis
    dès qu'un Directeur ou un client externe peut demander "qui a fait quoi".

    (Anciennement dans un fichier "user rbac.py" mal nommé — espace dans le
    nom de fichier, donc jamais importable par `import` standard : la classe
    n'était enregistrée nulle part et la table n'existait dans aucun schéma
    SQL. Déplacée ici, aux côtés des autres tables opérationnelles v2.)
    """

    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("dim_user.id"))
    action = Column(String(50), nullable=False)  # login|node_updated|report_exported...
    entity_type = Column(String(50))  # node|incident|user|maintenance_window...
    entity_id = Column(String(50))
    ip_address = Column(String(50))
    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User")