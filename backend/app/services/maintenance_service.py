"""dim_maintenance_window : création manuelle (dashboard) et import
automatique (ETL) — voir models/dimension.py::MaintenanceWindow pour la
distinction des deux origines."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.dimension import MaintenanceWindow, Node
from app.schemas.maintenance import MaintenanceWindowCreate, MaintenanceWindowImportPayload

logger = logging.getLogger(__name__)

# Certains outils (NetXMS, et Centreon pour la partie active_till — voir
# extract/centreon.py) ne rapportent qu'un drapeau on/off, sans horaires. Une
# fenêtre sans ends_at ne suffit à rien (elle ne suppprimerait jamais les
# alertes) : on lui donne une durée par défaut, régulièrement reconduite tant
# que le poll suivant la voit encore active (upsert sur external_id).
_DEFAULT_WINDOW_DURATION = timedelta(hours=1)


def create_maintenance_window(
    db: Session, payload: MaintenanceWindowCreate, created_by_user_id: int
) -> MaintenanceWindow:
    window = MaintenanceWindow(
        node_id=payload.node_id,
        locality_id=payload.locality_id,
        reason=payload.reason,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        suppress_alerts=payload.suppress_alerts,
        created_by_user_id=created_by_user_id,
    )
    db.add(window)
    db.commit()
    db.refresh(window)
    return window


def list_active_windows(db: Session) -> list[MaintenanceWindow]:
    """Fenêtres dont la période couvre l'instant présent — manuelles et
    importées confondues, triées par fin la plus proche d'abord (les plus
    urgentes à surveiller/prolonger en premier)."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return (
        db.query(MaintenanceWindow)
        .filter(MaintenanceWindow.starts_at <= now, MaintenanceWindow.ends_at >= now)
        .order_by(MaintenanceWindow.ends_at.asc())
        .all()
    )


def ingest_maintenance_windows_bulk(
    db: Session, payloads: list[MaintenanceWindowImportPayload]
) -> dict[str, int]:
    """Upsert sur (source_tool, external_id) — voir
    normalize.to_maintenance_window_payload() côté ETL pour la construction
    de cet external_id stable. Un import qui revoit la même fenêtre encore
    active à chaque poll (5 min) met juste à jour ends_at au lieu de créer
    une nouvelle ligne à chaque fois.
    """
    if not payloads:
        return {"received": 0, "created": 0, "updated": 0, "unknown_node": 0}

    node_ids = {
        code: nid
        for code, nid in db.query(Node.code, Node.id).filter(
            Node.code.in_({p.node_code for p in payloads})
        )
    }

    existing = {
        (w.source_tool, w.external_id): w
        for w in db.query(MaintenanceWindow).filter(
            MaintenanceWindow.source_tool.in_({p.source_tool for p in payloads}),
            MaintenanceWindow.external_id.in_({p.external_id for p in payloads}),
        )
    }

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    created = updated = unknown_node = 0
    for p in payloads:
        node_id = node_ids.get(p.node_code)
        if node_id is None:
            unknown_node += 1
            continue

        starts_at = (
            p.starts_at.astimezone(timezone.utc).replace(tzinfo=None) if p.starts_at and p.starts_at.tzinfo else (p.starts_at or now)
        )
        ends_at = (
            p.ends_at.astimezone(timezone.utc).replace(tzinfo=None) if p.ends_at and p.ends_at.tzinfo else p.ends_at
        )
        if ends_at is None:
            ends_at = now + _DEFAULT_WINDOW_DURATION

        key = (p.source_tool, p.external_id)
        window = existing.get(key)
        if window is None:
            window = MaintenanceWindow(source_tool=p.source_tool, external_id=p.external_id)
            db.add(window)
            existing[key] = window
            created += 1
        else:
            updated += 1

        window.node_id = node_id
        window.reason = p.reason
        window.starts_at = starts_at
        window.ends_at = ends_at
        window.suppress_alerts = True

    db.commit()
    return {
        "received": len(payloads),
        "created": created,
        "updated": updated,
        "unknown_node": unknown_node,
    }
