"""
Veilleur d'incidents — remplace l'ancienne ingestion par webhook.

POURQUOI CE MODULE EXISTE
-------------------------
Dans l'ancienne architecture, l'ETL appelait `POST /api/incidents/ingest`
et c'est ce point d'entrée qui déclenchait la diffusion WebSocket, les
notifications SMS/e-mail et le push navigateur. Le nouvel ETL n'appelle
plus le backend : il écrit directement dans `fact_incident`
(etl/load/load_facts.py). Sans ce module, plus rien ne déclencherait
d'alerte — le dashboard afficherait les incidents, mais seulement quand
l'utilisateur rafraîchit la page.

Le veilleur interroge donc périodiquement l'entrepôt et joue le rôle que
tenait l'endpoint d'ingestion. Ce n'est pas un pis-aller : découpler la
détection de l'écriture rend le backend indifférent à la manière dont les
incidents arrivent, et un incident inséré à la main en SQL déclenche les
mêmes alertes qu'un incident collecté.

POURQUOI DU POLLING ET PAS `LISTEN/NOTIFY`
------------------------------------------
PostgreSQL sait notifier en temps réel via LISTEN/NOTIFY, mais cela
exigerait un TRIGGER sur `fact_incident` — donc une modification d'un
objet appartenant à l'ETL, ce que ce backend s'interdit. Un passage
toutes les 30 secondes est très en-dessous de l'intervalle de collecte de
l'ETL (300 s par défaut) : le veilleur n'est jamais le maillon lent.

IDEMPOTENCE
-----------
`ops_incident_notified` mémorise ce qui a déjà été signalé. Sans cette
table, chaque passage re-notifierait tous les incidents critiques encore
ouverts — soit une alerte SMS toutes les 30 secondes par incident.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.core.config import (
    WATCHER_INTERVAL_S,
    WATCHER_NOTIFY_SEVERITIES,
)
from app.db.session import SessionLocal
from app.services import cache_service, kpi_service
from app.services.alert_broadcaster import publish_alert

logger = logging.getLogger(__name__)

# Au démarrage, on ne remonte pas tout l'historique : seuls les incidents
# des dernières heures sont considérés comme « nouveaux ». Sans cette
# borne, un premier lancement après plusieurs jours d'arrêt inonderait le
# canal d'alertes et les destinataires SMS.
BOOTSTRAP_LOOKBACK_HOURS = 2


def _fetch_new_incidents(db, since: datetime) -> list[dict]:
    """Incidents jamais notifiés, détectés depuis `since`."""
    rows = db.execute(
        text(
            """
            SELECT
                i.id,
                i.source_tool,
                i.external_id,
                i.node_id,
                COALESCE(i.node_code, '—') AS node_code,
                COALESCE(i.node_name, '—') AS node_name,
                i.locality_id,
                COALESCE(i.locality, '—')  AS locality,
                i.severity,
                i.status,
                i.description,
                i.cause_category,
                i.cause_label,
                i.detected_at
            FROM v_incident i
            LEFT JOIN ops_incident_notified n ON n.incident_id = i.id
            WHERE n.incident_id IS NULL
              AND i.detected_at >= :since
              AND i.status IN ('open','acknowledged')
              AND NOT i.is_maintenance
            ORDER BY i.severity_rank ASC, i.detected_at ASC
            LIMIT 200
            """
        ),
        {"since": since},
    ).mappings().all()
    return [dict(r) for r in rows]


def _mark_notified(db, incident_ids: list[int]) -> None:
    if not incident_ids:
        return
    db.execute(
        text(
            """
            INSERT INTO ops_incident_notified (incident_id)
            SELECT unnest(CAST(:ids AS INT[]))
            ON CONFLICT (incident_id) DO NOTHING
            """
        ),
        {"ids": incident_ids},
    )
    db.commit()


def run_once(since: datetime | None = None) -> int:
    """Un passage du veilleur. Retourne le nombre d'incidents traités.

    Ne lève jamais : une erreur ici ne doit pas tuer la boucle de fond
    ni, a fortiori, l'API.
    """
    db = SessionLocal()
    try:
        since = since or datetime.now(UTC) - timedelta(hours=BOOTSTRAP_LOOKBACK_HOURS)
        incidents = _fetch_new_incidents(db, since)
        if not incidents:
            return 0

        notified_ids = []
        for incident in incidents:
            # Diffusion WebSocket pour TOUS les nouveaux incidents : le
            # mur d'alertes doit tout voir.
            publish_alert(
                {
                    "type": "incident",
                    "id": incident["id"],
                    "node_code": incident["node_code"],
                    "node_name": incident["node_name"],
                    "locality": incident["locality"],
                    "severity": incident["severity"],
                    "status": incident["status"],
                    "description": incident["description"],
                    "cause_label": incident["cause_label"],
                    "source_tool": incident["source_tool"],
                    "detected_at": (
                        incident["detected_at"].isoformat()
                        if incident["detected_at"]
                        else None
                    ),
                }
            )

            # Notifications sortantes (SMS/e-mail/push) réservées aux
            # sévérités configurées : réveiller une astreinte pour un
            # incident « low » la conduirait à ignorer les suivantes.
            if incident["severity"] in WATCHER_NOTIFY_SEVERITIES:
                _notify(incident)

            notified_ids.append(incident["id"])

        _mark_notified(db, notified_ids)
        kpi_service.invalidate_cache()
        cache_service.invalidate_prefix("noc:alerts:")

        logger.info("Veilleur : %d nouvel(aux) incident(s) diffusé(s)", len(notified_ids))
        return len(notified_ids)

    except Exception as exc:
        logger.exception("Passage du veilleur en échec : %s", exc)
        return 0
    finally:
        db.close()


def _notify(incident: dict) -> None:
    """Notifications sortantes. Importées tardivement pour que le
    veilleur reste fonctionnel même si Twilio/pywebpush ne sont pas
    installés dans l'environnement."""
    try:
        from app.services import notification_service, push_service

        notification_service.notify_critical_incident(
            incident_id=incident["id"],
            node_code=incident["node_code"],
            node_name=incident["node_name"],
            locality=incident["locality"],
            severity=incident["severity"],
            description=incident["description"],
        )
        push_service.notify_critical_incident_push(
            incident_id=incident["id"],
            node_code=incident["node_code"],
            node_name=incident["node_name"],
            severity=incident["severity"],
            description=incident["description"],
        )
    except Exception as exc:
        logger.error("Notification de l'incident #%s en échec : %s", incident["id"], exc)


async def watcher_loop() -> None:
    """Boucle de fond, démarrée par le cycle de vie de l'application."""
    logger.info("Veilleur d'incidents démarré (intervalle %ds)", WATCHER_INTERVAL_S)
    # Premier passage avec la fenêtre de rattrapage, puis fenêtre glissante
    # calée sur l'intervalle avec une marge de sécurité (facteur 4) pour
    # absorber une collecte ETL en retard sans manquer d'incident.
    since = datetime.now(UTC) - timedelta(hours=BOOTSTRAP_LOOKBACK_HOURS)
    while True:
        try:
            await asyncio.to_thread(run_once, since)
            since = datetime.now(UTC) - timedelta(seconds=WATCHER_INTERVAL_S * 4)
        except asyncio.CancelledError:
            logger.info("Veilleur d'incidents arrêté")
            raise
        except Exception as exc:
            logger.exception("Erreur inattendue dans la boucle du veilleur : %s", exc)
        await asyncio.sleep(WATCHER_INTERVAL_S)
