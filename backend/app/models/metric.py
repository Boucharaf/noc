"""fact_metric — métriques de performance et de disponibilité, en série
temporelle. Voir database/02_kpi_extensions.sql pour le schéma et la
justification (une seule table pour les deux types de lecture)."""

from sqlalchemy import BigInteger, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base


class Metric(Base):
    __tablename__ = "fact_metric"

    id = Column(BigInteger, primary_key=True)
    node_id = Column(Integer, ForeignKey("dim_node.id"), nullable=False)
    source_tool = Column(String(20), nullable=False)
    metric_type = Column(String(30), nullable=False)
    value = Column(Float, nullable=False)
    unit = Column(String(20))
    collected_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    node = relationship("Node")
