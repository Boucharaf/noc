FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Africa/Ouagadougou

WORKDIR /app

# libpq pour psycopg2 ; curl pour le HEALTHCHECK
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 curl \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY sql ./sql
# Outils d'exploitation, indispensables dans l'image : au premier
# démarrage, créer un compte est IMPOSSIBLE par l'API (elle exige d'être
# déjà connecté en directeur ou chef NOC). `docker compose exec backend
# python scripts/create_user.py` est le seul chemin d'amorçage.
COPY scripts ./scripts

# Répertoire des rapports générés (REPORT_OUTPUT_DIR)
RUN mkdir -p /var/lib/noc/reports

# L'API ne tourne pas en root : une faille dans une dépendance ne doit
# pas donner les droits d'administration du conteneur.
RUN useradd --system --create-home noc && chown -R noc:noc /app /var/lib/noc
USER noc

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8000/api/health || exit 1

# Un seul worker : le veilleur d'incidents tourne dans le cycle de vie de
# l'application. Avec plusieurs workers, chacun lancerait le sien et les
# alertes seraient diffusées en double. Pour monter en charge, utiliser
# plusieurs workers avec WATCHER_ENABLED=false et un unique conteneur
# dédié au veilleur.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
