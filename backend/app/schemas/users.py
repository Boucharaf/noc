"""Schémas Pydantic pour les utilisateurs.

RoleEnum est la seule chose définie ici : c'est la source de vérité pour les
4 rôles côté Pydantic, importée par schemas/auth.py. UserCreate/UserUpdate
vivaient auparavant en double ici ET dans schemas/auth.py (deux définitions
divergentes du même formulaire) — cette copie n'était importée nulle part
dans le code actif ; supprimée pour éviter que les deux dérivent à nouveau.
Les schémas de formulaire réellement utilisés par app/routes/users.py sont
dans schemas/auth.py.
"""

from enum import Enum


class RoleEnum(str, Enum):
    directeur = "directeur"
    chef_noc = "chef_noc"
    technicien = "technicien"
    agent_terrain = "agent_terrain"


