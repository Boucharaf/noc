from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.dimension import Locality, Node
from app.models.incident import Incident


def get_open_alerts(db: Session, limit: int = 20) -> list[dict]:
    rows = (
        db.execute(
            select(
                Incident.id,
                Node.code.label("node_code"),
                Node.name.label("node_name"),
                Locality.name.label("locality"),
                Incident.severity,
                Incident.status,
                Incident.description,
                Incident.detected_at,
                Incident.itop_ticket_id,
            )
            .join(Node, Incident.node_id == Node.id)
            .join(Locality, Node.locality_id == Locality.id)
            .where(Incident.status.in_(("open", "acknowledged")))
            .order_by(Incident.detected_at.asc())
            .limit(limit)
        )
        .mappings()
        .all()
    )

    now = datetime.now(timezone.utc)
    result = []
    for r in rows:
        detected_at = r["detected_at"]
        detected_at_aware = (
            detected_at.replace(tzinfo=timezone.utc)
            if detected_at.tzinfo is None
            else detected_at
        )
        age_minutes = int((now - detected_at_aware).total_seconds() // 60)
        result.append(
            {
                "id": r["id"],
                "node_code": r["node_code"],
                "node_name": r["node_name"],
                "locality": r["locality"],
                "severity": r["severity"],
                "status": r["status"],
                "description": r["description"],
                "detected_at": detected_at,
                "age_minutes": max(age_minutes, 0),
                "itop_ticket_id": r["itop_ticket_id"],
            }
        )
    return result
