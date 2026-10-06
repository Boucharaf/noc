# Image de provisionnement du laboratoire : elle ne tourne que quelques
# secondes, à la demande. Aucune dépendance hors bibliothèque standard —
# provision.py n'utilise que urllib et json, ce qui rend cette image
# triviale à construire et à auditer.
FROM python:3.12-slim

WORKDIR /app
COPY provision.py ./provision.py

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "/app/provision.py"]
