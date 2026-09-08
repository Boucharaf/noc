"""
Mur d'alertes du NOC.

Distinct de incident_service.list_incidents : celui-ci répond à « qu'est-ce
qui brûle en ce moment », pas « montre-moi l'historique ». Il ne renvoie
donc que des incidents non clos, triés par gravité puis par ancienneté,
et exclut les fenêtres de maintenance planifiée.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def get_open_alerts(
    db: Session,
    limit: int = 20,
    locality_id: int | None = None,
    severities: list[str] | None = None,
) -> list[dict]:
    where = [
        "i.status IN ('open','acknowledged')",
        "NOT i.is_maintenance",
    ]
    params: dict = {"limit": max(1, min(200, limit))}

    if locality_id is not None:
        where.append("i.locality_id = :locality_id")
        params["locality_id"] = locality_id
    if severities:
        where.append("i.severity = ANY(:severities)")
        params["severities"] = severities

    rows = db.execute(
        text(
            f"""
            SELECT
                i.id,
                COALESCE(i.node_code, '—') AS node_code,
                COALESCE(i.node_name, '—') AS node_name,
                i.node_id,
                i.locality_id,
                COALESCE(i.locality, '—')  AS locality,
                i.severity,
                i.status,
                i.source_tool,
                i.description,
                i.cause_category,
                i.cause_label,
                i.detected_at,
                i.acknowledged_at,
                a.assigned_to_user_id,
                u.full_name AS assigned_to_full_name,
                (EXTRACT(EPOCH FROM (now() - i.detected_at)) / 60)::INT AS age_minutes
            FROM v_incident i
            LEFT JOIN ops_incident_assignment a ON a.incident_id = i.id
            LEFT JOIN dim_user u ON u.id = a.assigned_to_user_id
            WHERE {' AND '.join(where)}
            ORDER BY i.severity_rank ASC, i.detected_at ASC NULLS LAST
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()

    return [dict(r) for r in rows]


def get_recent_alerts(db: Session, limit: int = 10) -> list[dict]:
    """Derniers incidents détectés, tous statuts confondus.

    Alimente la cloche de notifications : on veut y voir aussi ce qui
    vient d'être résolu, pas seulement ce qui reste ouvert.
    """
    rows = db.execute(
        text(
            """
            SELECT
                i.id,
                COALESCE(i.node_code, '—') AS node_code,
                COALESCE(i.node_name, '—') AS node_name,
                COALESCE(i.locality, '—')  AS locality,
                i.severity,
                i.status,
                i.source_tool,
                i.description,
                i.detected_at,
                (EXTRACT(EPOCH FROM (now() - i.detected_at)) / 60)::INT AS age_minutes
            FROM v_incident i
            WHERE NOT i.is_maintenance
            ORDER BY i.detected_at DESC NULLS LAST, i.id DESC
            LIMIT :limit
            """
        ),
        {"limit": max(1, min(100, limit))},
    ).mappings().all()

    return [dict(r) for r in rows]


def get_summary(db: Session, locality_id: int | None = None) -> dict:
    """Bandeau d'état du NOC : ce qui doit tenir en haut de chaque écran.

    Réunit en une requête ce que le frontend allait chercher en trois ou
    quatre appels : combien d'alertes par gravité, combien ne sont ni
    acquittées ni assignées, et depuis combien de temps la plus ancienne
    attend. Ce dernier chiffre est le vrai indicateur de tension d'un
    NOC — un total d'alertes stable peut cacher une alerte critique
    oubliée depuis six heures.
    """
    row = db.execute(
        text(
            """
            SELECT
                count(*)                                                   AS total_open,
                count(*) FILTER (WHERE i.severity = 'critical')            AS critical,
                count(*) FILTER (WHERE i.severity = 'high')                AS high,
                count(*) FILTER (WHERE i.severity = 'medium')              AS medium,
                count(*) FILTER (WHERE i.severity = 'low')                 AS low,
                count(*) FILTER (WHERE i.status = 'open')                  AS unacknowledged,
                count(*) FILTER (WHERE a.assigned_to_user_id IS NULL)      AS unassigned,
                count(*) FILTER (WHERE COALESCE(a.escalation_level, 0) > 0) AS escalated,
                count(*) FILTER (WHERE i.detected_at < now() - INTERVAL '24 hours') AS ageing,
                count(DISTINCT i.node_id)                                  AS nodes_affected,
                count(DISTINCT i.locality_id)                              AS localities_affected,
                min(i.detected_at) FILTER (WHERE i.status = 'open')        AS oldest_unacknowledged_at
            FROM v_incident i
            LEFT JOIN ops_incident_assignment a ON a.incident_id = i.id
            WHERE i.status IN ('open','acknowledged')
              AND NOT i.is_maintenance
              AND (CAST(:locality_id AS INT) IS NULL OR i.locality_id = :locality_id)
            """
        ),
        {"locality_id": locality_id},
    ).mappings().first()

    summary = {key: int(row[key] or 0) for key in (
        "total_open", "critical", "high", "medium", "low",
        "unacknowledged", "unassigned", "escalated", "ageing",
        "nodes_affected", "localities_affected",
    )}
    summary["oldest_unacknowledged_at"] = row["oldest_unacknowledged_at"]

    # Nombre d'alertes apparues sur les 60 dernières minutes : dit si la
    # situation s'aggrave en ce moment ou si l'on regarde un stock ancien.
    summary["opened_last_hour"] = int(
        db.execute(
            text(
                """
                SELECT count(*) FROM v_incident i
                WHERE i.detected_at > now() - INTERVAL '1 hour'
                  AND NOT i.is_maintenance
                  AND (CAST(:locality_id AS INT) IS NULL OR i.locality_id = :locality_id)
                """
            ),
            {"locality_id": locality_id},
        ).scalar()
        or 0
    )
    summary["resolved_last_hour"] = int(
        db.execute(
            text(
                """
                SELECT count(*) FROM v_incident i
                WHERE i.resolved_at > now() - INTERVAL '1 hour'
                  AND NOT i.is_maintenance
                  AND (CAST(:locality_id AS INT) IS NULL OR i.locality_id = :locality_id)
                """
            ),
            {"locality_id": locality_id},
        ).scalar()
        or 0
    )
    return summary


def count_open_by_severity(db: Session) -> dict[str, int]:
    rows = db.execute(
        text(
            """
            SELECT i.severity, count(*) AS nb
            FROM v_incident i
            WHERE i.status IN ('open','acknowledged') AND NOT i.is_maintenance
            GROUP BY i.severity
            """
        )
    ).mappings().all()
    return {r["severity"]: int(r["nb"]) for r in rows}
