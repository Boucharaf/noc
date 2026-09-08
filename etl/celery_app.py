"""
Déclaration de l'application Celery et de la planification (beat).

Planification :
    - collecte de chaque outil : toutes les COLLECT_INTERVAL_S secondes (300s par défaut)
    - recalcul des KPI de couverture de supervision : nuit à 02:00
    - rapport mensuel (PDF+DOCX) : le 1er de chaque mois à 02:30
"""
import os

from celery import Celery
from celery.schedules import crontab

from .config import settings

app = Celery(
    "noc_etl",
    broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1"),
    backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2"),
    # SANS `include`, le worker démarre normalement, se déclare en bonne
    # santé… et rejette chaque tâche que beat lui envoie avec
    # « Received unregistered task of type 'etl.pipelines.tasks...' ».
    # Le planificateur ne connaît que des NOMS ; c'est au worker d'avoir
    # importé les fonctions correspondantes. Le module des tâches n'étant
    # importé nulle part ailleurs (celery_app ne peut pas l'importer en
    # haut de fichier : tasks.py importe `app` depuis ici, ce qui ferait
    # un cycle), c'est cette liste qui le charge — au bon moment, une
    # fois l'application construite.
    include=["etl.pipelines.tasks"],
)

app.conf.beat_schedule = {
    "collect-all-tools": {
        "task": "etl.pipelines.tasks.collect_all_tools",
        "schedule": settings.collect_interval_s,
    },
    "refresh-supervision-coverage": {
        "task": "etl.pipelines.tasks.refresh_supervision_coverage",
        "schedule": crontab(hour=2, minute=0),
    },
    "monthly-report": {
        "task": "etl.pipelines.tasks.generate_monthly_report",
        "schedule": crontab(day_of_month=1, hour=2, minute=30),
    },
}
app.conf.timezone = "Africa/Ouagadougou"
