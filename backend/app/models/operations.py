"""
Modèles ORM des tables appartenant au backend.

`User` est un cas mixte : la table `dim_user` est créée par l'ETL
(etl/sql/schema_dimensions.sql) mais n'est peuplée que par le backend.
Les colonnes ajoutées par sql/01_backend_extensions.sql (pin_hash, scope
géographique, contact) sont déclarées ici et sont toutes nullables — un
ETL qui insérerait un utilisateur sans elles resterait valide.

Toutes les autres tables sont préfixées `ops_` : elles n'existent que
pour le backend, l'ETL n'en connaît aucune.
"""
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base


class User(Base):
    __tablename__ = "dim_user"

    id = Column(Integer, primary_key=True)
    username = Column(Text, unique=True, nullable=False)
    full_name = Column(Text)
    role = Column(Text, nullable=False, default="agent_terrain")
    password_hash = Column(Text)
    is_active = Column(Boolean, nullable=False, default=True)
    last_login_at = Column(DateTime(timezone=True))

    # --- colonnes ajoutées par sql/01_backend_extensions.sql ---
    pin_hash = Column(Text)
    region_id = Column(Integer, ForeignKey("dim_region.id"))
    locality_id = Column(Integer, ForeignKey("dim_locality.id"))
    ministry_id = Column(Integer, ForeignKey("dim_ministry.id"))
    phone_number = Column(Text)
    employee_code = Column(Text)
    team = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class IncidentTimeline(Base):
    __tablename__ = "ops_incident_timeline"

    id = Column(Integer, primary_key=True)
    incident_id = Column(Integer, ForeignKey("fact_incident.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("dim_user.id"))
    action = Column(Text, nullable=False)
    note = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User")


class IncidentAssignment(Base):
    """Assignation et escalade, hors de fact_incident.

    Volontairement dans une table à part : fact_incident est réécrite en
    UPSERT à chaque cycle de collecte par etl/load/load_facts.py. Une
    colonne `assigned_to_user_id` posée sur fact_incident survivrait
    jusqu'au prochain passage de l'ETL, puis serait silencieusement
    perdue. Ici, l'ETL ne touche à rien.
    """

    __tablename__ = "ops_incident_assignment"

    incident_id = Column(Integer, ForeignKey("fact_incident.id"), primary_key=True)
    assigned_to_user_id = Column(Integer, ForeignKey("dim_user.id"))
    escalation_level = Column(Integer, nullable=False, default=0)
    escalated_at = Column(DateTime(timezone=True))
    escalated_to_user_id = Column(Integer, ForeignKey("dim_user.id"))
    impact_scope = Column(Integer, nullable=False, default=1)
    incident_type = Column(Text)
    reopened_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), server_default=func.now())

    assigned_to = relationship("User", foreign_keys=[assigned_to_user_id])
    escalated_to = relationship("User", foreign_keys=[escalated_to_user_id])


class SlaTarget(Base):
    __tablename__ = "ops_sla_target"

    id = Column(Integer, primary_key=True)
    severity = Column(Text, unique=True, nullable=False)
    ttr_target_minutes = Column(Integer, nullable=False)
    tta_target_minutes = Column(Integer, nullable=False)
    availability_target_pct = Column(Float, nullable=False, default=99.0)


class MaintenanceWindow(Base):
    __tablename__ = "ops_maintenance_window"

    id = Column(Integer, primary_key=True)
    node_id = Column(Integer, ForeignKey("dim_node.id"))
    locality_id = Column(Integer, ForeignKey("dim_locality.id"))
    reason = Column(Text, nullable=False)
    starts_at = Column(DateTime(timezone=True), nullable=False)
    ends_at = Column(DateTime(timezone=True), nullable=False)
    suppress_alerts = Column(Boolean, nullable=False, default=True)
    created_by_user_id = Column(Integer, ForeignKey("dim_user.id"))
    source_tool = Column(Text)
    external_id = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class FieldIntervention(Base):
    __tablename__ = "ops_field_intervention"

    id = Column(Integer, primary_key=True)
    incident_id = Column(Integer, ForeignKey("fact_incident.id"))
    node_id = Column(Integer, ForeignKey("dim_node.id"), nullable=False)
    agent_user_id = Column(Integer, ForeignKey("dim_user.id"), nullable=False)
    status = Column(Text, nullable=False, default="scheduled")
    scheduled_at = Column(DateTime(timezone=True))
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    checkin_latitude = Column(Float)
    checkin_longitude = Column(Float)
    report_text = Column(Text)
    photo_urls = Column(JSONB, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PushSubscription(Base):
    __tablename__ = "ops_push_subscription"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("dim_user.id"), nullable=False)
    endpoint = Column(Text, unique=True, nullable=False)
    p256dh = Column(Text, nullable=False)
    auth = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class NotificationLog(Base):
    __tablename__ = "ops_notification_log"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("dim_user.id"))
    incident_id = Column(Integer, ForeignKey("fact_incident.id"))
    channel = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="sent")
    detail = Column(Text)
    sent_at = Column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "ops_audit_log"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("dim_user.id"))
    action = Column(Text, nullable=False)
    entity_type = Column(Text)
    entity_id = Column(Text)
    ip_address = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class IncidentNotified(Base):
    """Marqueur « incident déjà notifié », utilisé par le veilleur.

    Sans lui, chaque passage du veilleur re-notifierait tous les incidents
    critiques encore ouverts.
    """

    __tablename__ = "ops_incident_notified"

    incident_id = Column(Integer, ForeignKey("fact_incident.id"), primary_key=True)
    notified_at = Column(DateTime(timezone=True), server_default=func.now())
