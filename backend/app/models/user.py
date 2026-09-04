"""
dim_user — version 2 : 4 rôles distincts (Directeur, Chef NOC, Technicien,
Agent terrain), remplaçant l'ancien modèle à rôle unique.

Choix de conception : un champ `role` en chaîne contrainte (pas une table de
permissions séparée). Avec seulement 4 rôles fixes, une table role/permission
dynamique ajoute de la complexité sans bénéfice réel — la matrice de
permissions (qui fait quoi) est mieux gérée en code (voir
frontend/src/api/permissions.js, dont VALID_ROLES ci-dessous est le miroir
côté backend), pas en donnée. Si des rôles custom par client apparaissent un
jour, migrer vers une table dim_role + dim_permission devient justifié, pas
avant.

Ajouts par rapport à la v1 (rôle unique "noc_agent") :
- role désormais contraint aux 4 valeurs (voir VALID_ROLES / CHECK en DB)
- locality_id / region_id : scope géographique (un Agent Terrain n'est
  rattaché qu'à sa localité, un Chef NOC peut couvrir une région)
- phone_number : nécessaire pour SMS d'astreinte / rappel agent terrain
- employee_code, team : rattachement RH/organisationnel
- mfa_enabled : le Directeur/Chef NOC ont accès à des données sensibles,
  la MFA est recommandée au moins pour ces deux rôles
"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base

# Gardé en phase avec dim_user.role's CHECK constraint (database/01_schema.sql)
# et avec les slugs de rôle utilisés dans les appels require_role(...) des
# routes, et avec frontend/src/api/permissions.js's ROLES. Centralisé ici pour
# qu'un nouveau rôle ne s'ajoute qu'à un seul endroit côté backend.
VALID_ROLES = ("directeur", "chef_noc", "technicien", "agent_terrain")


class User(Base):
    __tablename__ = "dim_user"

    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    full_name = Column(String(150), nullable=False)
    role = Column(String(20), nullable=False, default="agent_terrain")
    password_hash = Column(String(100), nullable=False)
    pin_hash = Column(String(64), unique=True)  # login rapide (utile terrain/mobile)
    is_active = Column(Boolean, default=True)
    last_login_at = Column(DateTime)

    # --- scope + organisation (v2) ---
    region_id = Column(Integer, ForeignKey("dim_region.id"))  # scope Chef NOC
    locality_id = Column(Integer, ForeignKey("dim_locality.id"))  # scope Agent Terrain
    phone_number = Column(String(30))
    employee_code = Column(String(30))
    team = Column(String(50))
    mfa_enabled = Column(Boolean, default=False)

    created_at = Column(DateTime, server_default=func.now())

    region = relationship("Region")
    locality = relationship("Locality")
