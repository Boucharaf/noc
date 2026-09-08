"""
Modèles ORM des tables écrites par l'ETL.

Chaque classe reproduit EXACTEMENT le DDL de etl/sql/*.sql — pas une
colonne de plus. Le backend ne fait jamais `Base.metadata.create_all()` :
ces tables sont créées par les scripts de l'ETL, ces modèles ne servent
qu'à les lire.

Points de vigilance issus du schéma ETL, à garder en tête partout dans le
backend :

* `dim_node` n'a PAS de colonne `code`, et `node_type` n'est jamais
  renseigné par etl/load/load_dimensions.py (l'INSERT ne le liste pas).
  Le frontend attend un `code` : la vue SQL `v_node` expose le nom comme
  code (voir sql/01_backend_extensions.sql).
* `dim_node.ministry_id` et `locality_id` sont NULLABLES et le restent
  tant que scripts/discover_geography.py n'a pas tourné. Tout agrégat
  géographique doit donc tolérer des nœuds sans site.
* `fact_incident.severity` et `.status` contiennent des valeurs BRUTES,
  différentes d'un outil à l'autre. Ne jamais filtrer dessus directement :
  passer par la vue `v_incident`, qui les normalise.
* `fact_incident.cause_category` est un TEXTE libre, pas une clé
  étrangère vers dim_cause.
"""
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Text,
)

from app.db.session import Base


class Ministry(Base):
    __tablename__ = "dim_ministry"

    id = Column(Integer, primary_key=True)
    external_ref = Column(Text, unique=True)  # org_id iTop
    name = Column(Text, nullable=False)


class Region(Base):
    __tablename__ = "dim_region"

    id = Column(Integer, primary_key=True)
    code = Column(Text, unique=True)
    name = Column(Text, nullable=False)


class Locality(Base):
    __tablename__ = "dim_locality"

    id = Column(Integer, primary_key=True)
    external_ref = Column(Text, unique=True)  # location_id iTop
    region_id = Column(Integer, ForeignKey("dim_region.id"))
    code = Column(Text)
    name = Column(Text, nullable=False)
    latitude = Column(Float)
    longitude = Column(Float)


class Node(Base):
    __tablename__ = "dim_node"

    id = Column(Integer, primary_key=True)
    ministry_id = Column(Integer, ForeignKey("dim_ministry.id"))
    locality_id = Column(Integer, ForeignKey("dim_locality.id"))
    name = Column(Text, nullable=False)
    ip_address = Column(Text)
    node_type = Column(Text)
    is_active = Column(Boolean, nullable=False, default=True)


class Link(Base):
    __tablename__ = "dim_link"

    id = Column(Integer, primary_key=True)
    node_a_id = Column(Integer, ForeignKey("dim_node.id"))
    node_b_id = Column(Integer, ForeignKey("dim_node.id"))
    code = Column(Text)
    bandwidth_capacity_mbps = Column(Float)


class NodeSourceMap(Base):
    """Correspondance d'identité inter-outils.

    C'est cette table, et non une colonne `source_tool` sur dim_node, qui
    dit quels outils supervisent un équipement — un même équipement peut
    y avoir plusieurs lignes. C'est aussi la définition de « supervisé »
    retenue par l'ETL pour le KPI de couverture
    (etl/load/load_facts.py::refresh_supervision_coverage).
    """

    __tablename__ = "dim_node_source_map"

    source_tool = Column(Text, primary_key=True)
    external_ref = Column(Text, primary_key=True)
    node_id = Column(Integer, ForeignKey("dim_node.id"), nullable=False)


class Cause(Base):
    __tablename__ = "dim_cause"

    id = Column(Integer, primary_key=True)
    category = Column(Text, unique=True, nullable=False)
    label = Column(Text)


class Incident(Base):
    __tablename__ = "fact_incident"

    id = Column(Integer, primary_key=True)
    source_tool = Column(Text, nullable=False)
    external_id = Column(Text, nullable=False)
    node_id = Column(Integer, ForeignKey("dim_node.id"))
    link_id = Column(Integer, ForeignKey("dim_link.id"))
    itop_ticket_ref = Column(Text)
    status = Column(Text, nullable=False, default="open")
    severity = Column(Text)
    cause_category = Column(Text)
    detected_at = Column(DateTime(timezone=True))
    acknowledged_at = Column(DateTime(timezone=True))
    resolved_at = Column(DateTime(timezone=True))
    mtta_minutes = Column(Float)
    mttr_minutes = Column(Float)
    downtime_minutes = Column(Float)
    description = Column(Text)


class SupervisionCoverageDaily(Base):
    __tablename__ = "fact_supervision_coverage_daily"

    date = Column(Date, primary_key=True)
    ministry_id = Column(Integer, ForeignKey("dim_ministry.id"), primary_key=True)
    locality_id = Column(Integer, ForeignKey("dim_locality.id"), primary_key=True)
    nb_equip_total = Column(Integer, nullable=False, default=0)
    nb_equip_supervised = Column(Integer, nullable=False, default=0)


class MetricValue(Base):
    """Hypertable TimescaleDB — pas de clé primaire réelle en base.

    La clé composite déclarée ici est artificielle : SQLAlchemy exige une
    PK pour mapper une classe. Elle n'est jamais utilisée pour écrire (le
    backend ne fait que lire cette table, l'ETL seul y insère).
    """

    __tablename__ = "metric_value"

    time = Column(DateTime(timezone=True), primary_key=True)
    node_id = Column(Integer, ForeignKey("dim_node.id"), primary_key=True)
    metric_type = Column(Text, primary_key=True)
    source_tool = Column(Text, primary_key=True, nullable=False)
    link_id = Column(Integer, ForeignKey("dim_link.id"))
    value = Column(Float, nullable=False)
