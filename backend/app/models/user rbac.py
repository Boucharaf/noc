"""
dim_user.py — version 2 : passage à 4 rôles distincts.

Choix de conception : un champ `role` en Enum (pas une table de permissions
séparée). Avec seulement 4 rôles fixes, une table role/permission dynamique
ajoute de la complexité sans bénéfice réel — la matrice de permissions
(qui fait ce qui, quel scope) est mieux gérée en code (voir permissions.py
plus bas), pas en donnée. Si un jour des rôles custom par client apparaissent,
migrer vers une table dim_role + dim_permission devient justifié, pas avant.

Ajouts :
- role désormais contraint aux 4 valeurs (Enum SQLAlchemy -> CHECK en DB)
- locality_id / region_id : scope géographique (un Agent Terrain n'est
  rattaché qu'à sa localité, un Chef NOC peut couvrir une région)
- phone_number : obligatoire pour SMS d'astreinte / rappel agent terrain
- employee_code, team : rattachement RH/organisationnel
- mfa_enabled : le Directeur/Chef NOC ont accès à des données sensibles,
  la MFA est recommandée au moins pour ces deux rôles
"""

import enum

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base


class UserRole(str, enum.Enum):
    DIRECTEUR = "directeur"  # vue stratégique, lecture seule, tous les KPI/SLA
    CHEF_NOC = "chef_noc"  # pilotage complet : assignation, escalade, rapports
    TECHNICIEN = "technicien"  # traite/résout les incidents qui lui sont assignés
    AGENT_TERRAIN = "agent_terrain"  # intervention physique sur site, mobile-first


class User(Base):
    __tablename__ = "dim_user"

    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    full_name = Column(String(150), nullable=False)
    role = Column(Enum(UserRole, native_enum=False, length=20), nullable=False, default=UserRole.AGENT_TERRAIN)
    password_hash = Column(String(100), nullable=False)
    pin_hash = Column(String(64), unique=True)  # login rapide (utile terrain/mobile)
    is_active = Column(Boolean, default=True)
    last_login_at = Column(DateTime)

    # --- ajouts scope + organisation ---
    region_id = Column(Integer, ForeignKey("dim_region.id"))  # scope Chef NOC
    locality_id = Column(Integer, ForeignKey("dim_locality.id"))  # scope Agent Terrain
    phone_number = Column(String(30))
    employee_code = Column(String(30))
    team = Column(String(50))
    mfa_enabled = Column(Boolean, default=False)

    created_at = Column(DateTime, server_default=func.now())

    region = relationship("Region")
    locality = relationship("Locality")


class AuditLog(Base):
    """Journal transverse (au-delà des incidents) : connexions, création/
    modification d'un nœud, changement de rôle, export de rapport... Requis
    dès qu'un Directeur ou un client externe peut demander "qui a fait quoi".
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


# --- matrice de permissions (code, pas donnée — voir note en tête de fichier) ---

PERMISSIONS = {
    UserRole.DIRECTEUR: {
        "view_kpi_global", "view_sla", "view_reports", "export_reports",
    },
    UserRole.CHEF_NOC: {
        "view_kpi_global", "view_sla", "view_reports", "export_reports",
        "assign_incident", "escalate_incident", "manage_maintenance_window",
        "manage_users_scope", "view_all_incidents",
    },
    UserRole.TECHNICIEN: {
        "view_assigned_incidents", "acknowledge_incident", "resolve_incident",
        "comment_incident", "escalate_incident",
    },
    UserRole.AGENT_TERRAIN: {
        "view_assigned_incidents_readonly", "submit_field_intervention",
        "acknowledge_incident",
    },
}