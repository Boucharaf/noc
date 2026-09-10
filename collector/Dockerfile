# Collecteur du NOC.
#
# Le contexte de construction est la RACINE du dépôt et non ce répertoire :
# l'image a besoin de `integrations/`, le paquet de connecteurs que le
# collecteur partage avec le backend (voir integrations/__init__.py). D'où,
# dans docker-compose.yml :
#
#     build:
#       context: .
#       dockerfile: collector/Dockerfile
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Les dépendances avant le code : une modification du collecteur ne réinstalle
# alors pas httpx et psycopg à chaque construction.
COPY collector/requirements.txt ./collector/requirements.txt
RUN pip install --no-cache-dir -r collector/requirements.txt

COPY integrations ./integrations
COPY collector ./collector

# Utilisateur non privilégié : le collecteur ne fait que des appels sortants
# et n'a aucune raison de tourner en root.
RUN useradd --system --create-home --uid 1001 noc \
    && chown -R noc:noc /app
USER noc

# Sain = le dernier cycle a moins de deux intervalles. Contrôler que le
# processus vit ne suffirait pas : une boucle asyncio peut rester en vie tout
# en ne publiant plus rien, et c'est précisément la panne qu'on veut voir.
HEALTHCHECK --interval=60s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "\
import json, os, sys, time, redis; \
r = redis.from_url(os.environ.get('REDIS_URL', 'redis://redis:6379/0'), decode_responses=True); \
raw = r.get('noc:live:meta'); \
sys.exit(0 if raw else 1)"

CMD ["python", "-m", "collector"]
