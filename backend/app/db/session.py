"""
Session SQLAlchemy sur l'entrepôt NOC.

Une seule base, celle de l'ETL. Le backend y est LECTEUR pour tout ce que
l'ETL produit (dim_*, fact_incident, metric_value) et ÉCRIVAIN uniquement
sur ses propres tables `ops_*` — plus l'exception documentée des incidents
manuels, écrits dans fact_incident avec source_tool='manual', une clé que
l'ETL ne produit jamais (contrainte UNIQUE (source_tool, external_id)).
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import DB_MAX_OVERFLOW, DB_POOL_SIZE, WAREHOUSE_DSN

# psycopg2 est le driver utilisé aussi par l'ETL : même famille de types,
# mêmes conversions de dates, moins de surprises entre les deux côtés.
DATABASE_URL = WAREHOUSE_DSN.replace("postgresql://", "postgresql+psycopg2://", 1)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,      # la connexion peut avoir été coupée entre deux collectes
    pool_size=DB_POOL_SIZE,
    max_overflow=DB_MAX_OVERFLOW,
    future=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
