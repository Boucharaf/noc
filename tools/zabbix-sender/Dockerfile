# zabbix-sender — pousse des mesures CPU/mémoire/débit RÉELLES (lues via
# l'API Docker) vers Zabbix par le protocole Sender. Voir sender.py pour le
# raisonnement complet.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY sender.py .

# Root, volontairement : lire /var/run/docker.sock l'exige. Aucune
# restriction de ce Dockerfile ne limite ce que ce conteneur PEUT faire par
# ce socket — un `:ro` sur le montage n'empêche que d'écrire sur le fichier
# spécial lui-même, pas les appels transmis à travers lui, qui restent le
# plein pouvoir de l'API Docker. La seule garantie ici vient du CODE :
# sender.py n'appelle que des méthodes en lecture (`containers.list`,
# `.stats`). Voir le commentaire du montage dans docker-compose.yml pour ce
# que ça implique réellement.
CMD ["python", "sender.py"]
