"""
Session SQLAlchemy sur la base du NOC.

CETTE BASE N'EST PLUS UN ENTREPÔT. Elle ne contient ni métriques, ni
inventaire, ni historique d'incidents : uniquement ce que le NOC produit
lui-même et qu'aucun outil source ne saurait redonner — comptes, travail
d'exploitation, maintenances, agrégats journaliers. Voir
backend/sql/schema.sql et ARCHITECTURE.md.

Conséquence sur le dimensionnement : elle ne sert PLUS le chemin chaud du
tableau de bord, qui lit Redis. Le pool est donc modeste (cinq connexions)
là où l'ancien entrepôt en réservait trente — trente connexions inactives
coûtent de la mémoire côté PostgreSQL sans rien apporter.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import DATABASE_URL, DB_MAX_OVERFLOW, DB_POOL_SIZE

# psycopg2 : le pilote synchrone. Le collecteur utilise psycopg 3 en
# asynchrone pour ses agrégats ; les deux cohabitent sans se gêner, chacun
# dans son processus.
SQLALCHEMY_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

engine = create_engine(
    SQLALCHEMY_URL,
    # La connexion peut avoir été coupée par un redémarrage de PostgreSQL ou
    # un pare-feu qui recycle les sessions inactives. Sans ce contrôle, la
    # première requête après la coupure échoue en 500.
    pool_pre_ping=True,
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
