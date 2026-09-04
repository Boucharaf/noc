"""
fact_incident + tables associées, version 2.

Ajouts sur fact_incident :
- assigned_to_user_id : qui traite (technicien/ingénieur)
- escalation_level / escalated_at / escalated_to_user_id : traçabilité de l'escalade
- sla_target_minutes / sla_breached : SLA calculé au moment de la clôture
- impact_scope : nb de sites/utilisateurs touchés (priorisation Chef NOC / Directeur)
- incident_type : réseau, matériel, électrique, logiciel, sécurité...
- parent_incident_id : corrélation (une panne WAN qui génère 40 alertes filles)
- reopened_count : qualité de la résolution

Nouvelle table fact_incident_timeline : journal d'audit (qui a fait quoi, quand),
indispensable pour un NOC "solide" — sans ça, aucune traçabilité des actions
humaines, seulement des timestamps de statut.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Computed,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base


class Incident(Base):
    __tablename__ = "fact_incident"

    id = Column(BigInteger, primary_key=True)
    node_id = Column(Integer, ForeignKey("dim_node.id"), nullable=False)
    cause_id = Column(Integer, ForeignKey("dim_cause.id"))
    itop_ticket_id = Column(String(50))
    external_id = Column(String(100))
    status = Column(String(20), nullable=False, default="open")
    severity = Column(String(20), nullable=False, default="medium")
    detected_at = Column(DateTime, nullable=False)
    acknowledged_at = Column(DateTime)
    resolved_at = Column(DateTime)
    # Ces deux expressions doivent rester identiques à celles de
    # database/01_schema.sql (colonnes générées côté Postgres) — Computed()
    # ici ne sert que de documentation ORM, la table réelle est créée par le
    # script SQL, pas par Base.metadata.create_all(). Les anciennes valeurs
    # ("0" / "'auto'" en dur) ne correspondaient plus au schéma réel depuis
    # l'ajout du calcul par shift/MTTR.
    mttr_minutes = Column(
        Integer, Computed("EXTRACT(EPOCH FROM (resolved_at - detected_at)) / 60")
    )
    downtime_minutes = Column(Integer, default=0)
    shift = Column(
        String(20),
        Computed(
            "CASE "
            "WHEN EXTRACT(HOUR FROM detected_at) BETWEEN 6 AND 21 THEN 'noc' "
            "WHEN EXTRACT(HOUR FROM detected_at) BETWEEN 7 AND 16 THEN 'terrain' "
            "ELSE 'auto' END"
        ),
    )
    source_tool = Column(String(20), nullable=False)
    description = Column(Text)

    # --- ajouts flux de traitement / rôles ---
    assigned_to_user_id = Column(Integer, ForeignKey("dim_user.id"))
    escalation_level = Column(Integer, default=0)  # 0=agent, 1=chef noc, 2=directeur
    escalated_at = Column(DateTime)
    escalated_to_user_id = Column(Integer, ForeignKey("dim_user.id"))

    # --- ajouts SLA / pilotage ---
    sla_target_minutes = Column(Integer)  # copié depuis fact_sla_target à la création
    sla_breached = Column(Boolean, default=False)
    impact_scope = Column(Integer, default=1)  # nb sites/équipements impactés
    incident_type = Column(String(30))  # network|hardware|power|software|security
    parent_incident_id = Column(BigInteger, ForeignKey("fact_incident.id"))
    reopened_count = Column(Integer, default=0)

    created_at = Column(DateTime, server_default=func.now())

    node = relationship("Node")
    cause = relationship("Cause")
    assigned_to = relationship("User", foreign_keys=[assigned_to_user_id])
    escalated_to = relationship("User", foreign_keys=[escalated_to_user_id])
    parent_incident = relationship("Incident", remote_side=[id])
    timeline = relationship("IncidentTimeline", back_populates="incident")


class IncidentTimeline(Base):
    """Journal d'audit d'un incident : chaque changement de statut, note,
    réassignation ou escalade y laisse une ligne. C'est ce qui permet au
    Chef NOC / Directeur de reconstituer le déroulé complet a posteriori,
    et sert de preuve en cas de contestation SLA avec un client/partenaire.
    """

    __tablename__ = "fact_incident_timeline"

    id = Column(BigInteger, primary_key=True)
    incident_id = Column(BigInteger, ForeignKey("fact_incident.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("dim_user.id"))  # null = événement système/ETL
    action = Column(
        String(30), nullable=False
    )  # created|acknowledged|assigned|escalated|commented|resolved|reopened|closed
    note = Column(Text)
    created_at = Column(DateTime, server_default=func.now())

    incident = relationship("Incident", back_populates="timeline")
    user = relationship("User")


class SLATarget(Base):
    """Objectifs SLA configurables (au lieu d'une valeur codée en dur dans
    l'app) : par sévérité, éventuellement par niveau de criticité de site.
    """

    __tablename__ = "dim_sla_target"

    id = Column(Integer, primary_key=True)
    severity = Column(String(20), nullable=False)
    locality_criticality_tier = Column(String(10))  # null = s'applique à tous
    target_minutes = Column(Integer, nullable=False)
    availability_target_pct = Column(Integer, default=99)