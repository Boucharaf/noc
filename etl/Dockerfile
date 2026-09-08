# Image de l'ETL NOC — utilisée à la fois par le worker Celery, par le
# planificateur (beat) et pour les scripts ponctuels (découverte
# géographique, restauration d'un dump source).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Africa/Ouagadougou

# Le paquet est copié dans /app/etl et NON à la racine de /app : les
# modules utilisent des imports relatifs (`from .config import settings`),
# qui n'ont de sens que si `etl` est importé comme un paquet. C'est aussi
# pourquoi les commandes Celery visent `etl.celery_app` et non
# `celery_app` — invoquer ce dernier casserait au premier import relatif.
WORKDIR /app

# libpq5 pour psycopg2-binary ; les autres paquets ne demandent rien de
# natif. Pas de build-essential : psycopg2-binary est distribué en roue
# précompilée, l'ajouter triplerait la taille de l'image pour rien.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./etl/

# Répertoire des rapports partagé avec le backend (volume `reports`).
RUN mkdir -p /reports

# L'ETL ne tourne pas en root : il ouvre des connexions vers six systèmes
# tiers, c'est la surface d'attaque la plus large du projet.
RUN useradd --system --create-home etl && chown -R etl:etl /app /reports
USER etl

# Par défaut : le worker. `docker compose` surcharge cette commande pour
# le planificateur (`celery -A etl.celery_app beat`).
CMD ["celery", "-A", "etl.celery_app", "worker", "--loglevel=INFO", "--concurrency=2"]
