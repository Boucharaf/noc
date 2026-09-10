#!/usr/bin/env python3
"""
Création d'un compte en ligne de commande.

Raison d'être : `POST /api/users` exige d'être déjà connecté en
chef_noc. Au premier démarrage aucun compte n'existe, donc personne ne
peut se connecter, donc personne ne peut créer de compte. Ce script
casse cette boucle — c'est le seul chemin de création qui ne passe pas
par l'API, et il doit rester réservé à l'amorçage (le premier Chef NOC,
qui crée ensuite tous les autres comptes depuis l'interface) et au
dépannage (mot de passe oublié du seul Chef NOC).

Usage :
    cd backend
    python scripts/create_user.py --username directeur --role directeur \\
        --full-name "Nom Prénom" --password "MotDePasse123"

    # Mot de passe demandé de façon masquée si --password est omis :
    python scripts/create_user.py -u chef -r chef_noc -n "Chef NOC"

    # Réinitialiser le mot de passe d'un compte existant :
    python scripts/create_user.py -u directeur --reset-password

    # Amorçage complet (un compte par rôle), pour une recette :
    python scripts/create_user.py --role-set --password "Test1234"

Variables lues : NOC_DATABASE_URL (ou POSTGRES_* en repli), exactement
comme le backend — voir app/core/config.py.
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

# Permet `python scripts/create_user.py` depuis backend/ sans installer
# le paquet : le répertoire parent contient `app/`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import DATABASE_URL, VALID_ROLES  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402
from app.services import auth_service  # noqa: E402

# Un compte par rôle métier, pour l'amorçage d'une plateforme neuve : les
# quatre tableaux de bord doivent être accessibles dès la première
# connexion. Ce ne sont pas des comptes de démonstration — ce sont les
# quatre rôles que le NOC exploite réellement, et l'exploitant les renomme.
ROLE_SET = (
    ("directeur", "directeur", "Direction générale"),
    ("chefnoc", "chef_noc", "Chef de salle NOC"),
    ("technicien", "technicien", "Technicien supervision"),
    ("terrain", "agent_terrain", "Agent terrain"),
)


def _upsert(session, *, username: str, role: str, full_name: str,
            password: str, pin: str | None, reset_only: bool) -> str:
    user = session.query(User).filter(User.username == username).first()

    if user is None:
        if reset_only:
            return f"! {username} : compte inexistant, rien à réinitialiser"
        user = User(
            username=username,
            full_name=full_name,
            role=role,
            password_hash=auth_service.hash_password(password),
            pin_hash=auth_service.hash_pin(pin) if pin else None,
            is_active=True,
        )
        session.add(user)
        return f"+ {username} ({role}) créé"

    user.password_hash = auth_service.hash_password(password)
    # Un compte désactivé dont on réinitialise le mot de passe est
    # forcément un compte qu'on veut réutiliser.
    user.is_active = True
    if not reset_only:
        user.full_name = full_name
        user.role = role
    if pin:
        user.pin_hash = auth_service.hash_pin(pin)
    return f"~ {username} mis à jour ({user.role})"


def main() -> int:
    parser = argparse.ArgumentParser(description="Création / réinitialisation d'un compte NOC.")
    parser.add_argument("-u", "--username")
    parser.add_argument("-n", "--full-name", default=None)
    parser.add_argument("-r", "--role", choices=VALID_ROLES)
    parser.add_argument("-p", "--password", default=None)
    parser.add_argument("--pin", default=None, help="PIN numérique 4-6 chiffres (connexion terrain)")
    parser.add_argument("--reset-password", action="store_true",
                        help="Ne change que le mot de passe d'un compte existant")
    parser.add_argument("--role-set", action="store_true",
                        help="Crée un compte par rôle (directeur/chefnoc/technicien/terrain)")
    parser.add_argument("--list", action="store_true", help="Liste les comptes existants et sort")
    args = parser.parse_args()

    print(f"Base du NOC : {DATABASE_URL.split('@')[-1]}")
    session = SessionLocal()
    try:
        if args.list:
            users = session.query(User).order_by(User.role, User.username).all()
            if not users:
                print("Aucun compte. Utilisez --role-set ou -u/-r pour en créer un.")
            for u in users:
                state = "actif" if u.is_active else "désactivé"
                pin = ", PIN" if u.pin_hash else ""
                print(f"  {u.username:<16} {u.role:<14} {state}{pin}  — {u.full_name or ''}")
            return 0

        if args.role_set:
            password = args.password or getpass.getpass("Mot de passe commun aux 4 comptes : ")
            if len(password) < 8:
                print("Le mot de passe doit faire au moins 8 caractères.", file=sys.stderr)
                return 2
            for index, (username, role, full_name) in enumerate(ROLE_SET):
                # PIN distinct par compte : deux comptes partageant le même
                # PIN entreraient en collision sur l'index unique
                # idx_dim_user_pin_hash (le hash n'est pas salé).
                print(_upsert(session, username=username, role=role, full_name=full_name,
                              password=password, pin=f"{1000 + index * 111}", reset_only=False))
            session.commit()
            print("\nComptes prêts. Connexion : identifiant ci-dessus + le mot de passe saisi.")
            return 0

        if not args.username:
            parser.error("--username est requis (ou utilisez --role-set / --list)")
        if not args.reset_password and not args.role:
            parser.error("--role est requis à la création")

        password = args.password or getpass.getpass(f"Mot de passe pour {args.username} : ")
        if len(password) < 8:
            print("Le mot de passe doit faire au moins 8 caractères.", file=sys.stderr)
            return 2

        print(_upsert(
            session,
            username=args.username,
            role=args.role or "",
            full_name=args.full_name or args.username,
            password=password,
            pin=args.pin,
            reset_only=args.reset_password,
        ))
        session.commit()
        return 0
    except Exception as exc:  # pragma: no cover - outil d'exploitation
        session.rollback()
        print(f"Échec : {exc}", file=sys.stderr)
        if "does not exist" in str(exc) or "n'existe pas" in str(exc):
            print(
                "\nTable ou colonne absente : le schéma de la base est en retard.\n"
                "Il se rejoue sans danger sur une base en service :\n"
                "  docker compose exec -T postgres psql -U noc -d noc < backend/sql/schema.sql",
                file=sys.stderr,
            )
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
