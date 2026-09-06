"""dim_asset — référentiel du parc total d'équipements, indépendant des
outils de supervision (voir database/02_kpi_extensions.sql). is_monitored et
node_id sont mis à jour par asset_service.sync_assets_bulk quand un CI est
rapproché d'un dim_node existant ; tant que ce n'est pas le cas, l'actif est
compté comme non supervisé — c'est la donnée que le KPI "taux de couverture"
n'a jamais pu calculer sans cette table."""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base


class Asset(Base):
    __tablename__ = "dim_asset"

    id = Column(Integer, primary_key=True)
    locality_id = Column(Integer, ForeignKey("dim_locality.id"))
    itop_ci_id = Column(String(50), unique=True, nullable=False)
    name = Column(String(200), nullable=False)
    asset_type = Column(String(50))
    is_monitored = Column(Boolean, nullable=False, default=False)
    node_id = Column(Integer, ForeignKey("dim_node.id"))
    last_synced_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())

    locality = relationship("Locality")
    node = relationship("Node")
