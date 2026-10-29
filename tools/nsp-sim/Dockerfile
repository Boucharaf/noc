# Simulateur Nokia NSP — laboratoire local uniquement (voir sim.py).
# Bibliothèque standard seule : aucune dépendance à installer.
FROM python:3.12-slim

WORKDIR /app
COPY sim.py scenario.json ./
RUN useradd --system --no-create-home nsp
USER nsp

EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/_sim/health', timeout=3)"
CMD ["python", "-u", "sim.py"]
