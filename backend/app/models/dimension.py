"""
dim_*.py — modèles de dimension, version 2.

Changements par rapport à la version initiale :
- dim_locality : infos terrain (contact, accès, criticité, secours électrique)
- dim_node : traçabilité matérielle + topologie (parent_node_id) + criticité
- dim_cause : marquage des causes récurrentes + lien playbook
- Nouvelle table dim_node_monitoring_source : un nœud peut être vu par
  PLUSIEURS outils (Zabbix + iTop + NetXMS...), source_tool sur dim_node
  reste comme "source primaire" pour compat descendante.
- Nouvelle table dim_maintenance_window : fenêtres de maintenance planifiées,
  pour suppression des faux positifs / SLA.
"""

from sqlalchemy import (
    Boolean,
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


class Region(Base):
    __tablename__ = "dim_region"

    id = Column(Integer, primary_key=True)
    code = Column(String(10), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    localities = relationship("Locality", back_populates="region")


class Province(Base):
    """Découpage administratif intermédiaire région → province → site,
    nécessaire pour le drill-down demandé (KPI global → ministère → province
    → site → équipement → incident). Voir database/02_kpi_extensions.sql."""

    __tablename__ = "dim_province"

    id = Column(Integer, primary_key=True)
    region_id = Column(Integer, ForeignKey("dim_region.id"), nullable=False)
    code = Column(String(10), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    region = relationship("Region")
    localities = relationship("Locality", back_populates="province")


class Organisation(Base):
    """Ministère / structure rattachée propriétaire d'un site — permet
    "disponibilité par ministère", absent du schéma initial."""

    __tablename__ = "dim_organisation"

    id = Column(Integer, primary_key=True)
    code = Column(String(20), unique=True, nullable=False)
    name = Column(String(200), nullable=False)
    org_type = Column(String(30))
    created_at = Column(DateTime, server_default=func.now())

    localities = relationship("Locality", back_populates="organisation")


class Locality(Base):
    __tablename__ = "dim_locality"

    id = Column(Integer, primary_key=True)
    region_id = Column(Integer, ForeignKey("dim_region.id"), nullable=False)
    code = Column(String(10), unique=True, nullable=False)
    name = Column(String(150), nullable=False)
    latitude = Column(Numeric(9, 6))
    longitude = Column(Numeric(9, 6))
    population = Column(Integer, default=0)

    # --- ajouts NOC terrain ---
    site_type = Column(String(30))  # datacenter, relais, antenne, agence...
    criticality_tier = Column(String(10), default="T3")  # T1 (vital) -> T3
    has_backup_power = Column(Boolean, default=False)  # groupe électrogène / onduleur
    address = Column(Text)  # nécessaire pour dépêcher un agent terrain
    access_notes = Column(Text)  # code portail, contact gardien, horaires d'accès
    contact_name = Column(String(150))
    contact_phone = Column(String(30))

    # --- ajouts hiérarchie organisationnelle ---
    province_id = Column(Integer, ForeignKey("dim_province.id"))
    organisation_id = Column(Integer, ForeignKey("dim_organisation.id"))

    created_at = Column(DateTime, server_default=func.now())

    region = relationship("Region", back_populates="localities")
    province = relationship("Province", back_populates="localities")
    organisation = relationship("Organisation", back_populates="localities")
    nodes = relationship("Node", back_populates="locality")


class Node(Base):
    __tablename__ = "dim_node"

    id = Column(Integer, primary_key=True)
    locality_id = Column(Integer, ForeignKey("dim_locality.id"), nullable=False)
    code = Column(String(20), unique=True, nullable=False)
    name = Column(String(200), nullable=False)
    node_type = Column(String(50), nullable=False)
    ip_address = Column(String(50))
    source_tool = Column(String(20), nullable=False)  # outil "maître" historique
    itop_ci_id = Column(String(50))
    is_active = Column(Boolean, default=True)

    # --- ajouts traçabilité matérielle ---
    vendor = Column(String(100))
    model = Column(String(100))
    serial_number = Column(String(100))
    firmware_version = Column(String(50))
    installed_at = Column(DateTime)
    warranty_expiry_at = Column(DateTime)

    # --- ajouts NOC opérationnel ---
    criticality_tier = Column(String(10), default="T3")  # priorise l'écran superviseur
    parent_node_id = Column(Integer, ForeignKey("dim_node.id"))  # topologie / dépendance
    rack_location = Column(String(100))
    last_seen_at = Column(DateTime)  # dernier heartbeat toutes sources confondues

    created_at = Column(DateTime, server_default=func.now())

    locality = relationship("Locality", back_populates="nodes")
    parent_node = relationship("Node", remote_side=[id])
    monitoring_sources = relationship("NodeMonitoringSource", back_populates="node")


class NodeMonitoringSource(Base):
    """Un nœud physique peut être supervisé par plusieurs outils à la fois
    (ex: Zabbix pour le monitoring temps réel + iTop pour le ticketing).
    Sert aussi à détecter/dédupliquer les doublons d'équipements entre outils.
    """

    __tablename__ = "dim_node_monitoring_source"

    id = Column(Integer, primary_key=True)
    node_id = Column(Integer, ForeignKey("dim_node.id"), nullable=False)
    tool = Column(String(20), nullable=False)  # zabbix|nagios|netxms|centreon|itop
    external_id = Column(String(100), nullable=False)  # hostid/CI id côté outil
    is_primary = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())

    node = relationship("Node", back_populates="monitoring_sources")


class Cause(Base):
    __tablename__ = "dim_cause"

    id = Column(Integer, primary_key=True)
    category = Column(String(50), nullable=False)
    label = Column(String(150), nullable=False)

    # --- ajouts ---
    is_recurring = Column(Boolean, default=False)  # flaggé après N occurrences (job nightly)
    playbook_url = Column(Text)  # lien vers la procédure de résolution standard


class MaintenanceWindow(Base):
    """Fenêtre de maintenance planifiée. Un incident détecté sur un nœud/site
    dont la fenêtre est active doit être marqué 'maintenance' plutôt que
    remonté comme alerte critique (évite le bruit et les faux SLA breach).

    Deux origines possibles depuis l'extension 02_kpi_extensions.sql :
    - manuelle (created_by_user_id renseigné, source_tool/external_id nuls) —
      créée depuis le dashboard par un opérateur ;
    - importée automatiquement par l'ETL (source_tool/external_id renseignés,
      created_by_user_id nul) — détectée dans Zabbix/Centreon/NetXMS.
    Le CHECK chk_maintenance_origin en base impose l'un ou l'autre, jamais
    un mélange incohérent des deux.
    """

    __tablename__ = "dim_maintenance_window"

    id = Column(Integer, primary_key=True)
    node_id = Column(Integer, ForeignKey("dim_node.id"))  # nullable si site entier
    locality_id = Column(Integer, ForeignKey("dim_locality.id"))  # nullable si nœud unique
    reason = Column(Text, nullable=False)
    starts_at = Column(DateTime, nullable=False)
    ends_at = Column(DateTime, nullable=False)
    suppress_alerts = Column(Boolean, default=True)
    created_by_user_id = Column(Integer, ForeignKey("dim_user.id"), nullable=True)
    source_tool = Column(String(20))  # NULL = créée manuellement
    external_id = Column(String(100))  # NULL = créée manuellement
    created_at = Column(DateTime, server_default=func.now())