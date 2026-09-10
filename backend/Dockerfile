# API du NOC.
#
# Le contexte de construction est la RACINE du dépôt et non `backend/` :
# l'image a besoin de deux paquets qui vivent au-dessus —
#
#   integrations/  les connecteurs vers les outils sources, que le backend
#                  utilise pour la fédération d'historique (une courbe est
#                  lue chez Zabbix quand un exploitant l'ouvre) ;
#   collector/     pour `collector.state.SnapshotStore` seul, le contrat de
#                  clés Redis. Le collecteur écrit, le backend lit ; les
#                  deux DOIVENT partager la même définition, sinon un
#                  renommage de clé d'un côté rend le tableau de bord vide
#                  de l'autre, sans erreur.
#
# D'où, dans docker-compose.yml :
#
#     build:
#       context: .
#       dockerfile: backend/Dockerfile
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Africa/Ouagadougou

WORKDIR /app

# libpq pour psycopg2 ; curl pour le HEALTHCHECK.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 curl \
 && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/sql ./sql
# Outils d'exploitation, indispensables dans l'image : au premier démarrage,
# créer un compte est IMPOSSIBLE par l'API (elle exige d'être déjà connecté
# en chef NOC). `docker compose exec backend python
# scripts/create_user.py` est le seul chemin d'amorçage.
COPY backend/scripts ./scripts

COPY integrations ./integrations
COPY collector ./collector

RUN mkdir -p /var/lib/noc/reports

# L'API ne tourne pas en root : une faille dans une dépendance ne doit pas
# donner les droits d'administration du conteneur.
RUN useradd --system --create-home noc && chown -R noc:noc /app /var/lib/noc
USER noc

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8000/api/health/live || exit 1

# PLUSIEURS WORKERS SONT DÉSORMAIS POSSIBLES. L'ancien backend hébergeait le
# veilleur d'incidents dans son cycle de vie : chaque worker lançait le sien
# et les alertes partaient en double, d'où l'obligation d'un worker unique.
# La détection des nouveautés est passée dans le collecteur, et la
# notification est protégée par une contrainte d'unicité en base
# (ops_alert_notified) — plusieurs workers, et même plusieurs conteneurs,
# peuvent cohabiter sans qu'une alerte soit notifiée deux fois.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
