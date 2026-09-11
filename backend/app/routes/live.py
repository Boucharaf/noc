"""
Routes de l'état courant — équipements, alertes, synthèses.

TOUTES CES ROUTES LISENT REDIS, jamais la base ni les outils sources. C'est
ce qui permet au tableau de bord de se rafraîchir toutes les dix secondes
chez quarante opérateurs sans que les outils de production s'en aperçoivent.

TRAITEMENT DE L'INSTANTANÉ ABSENT. Quand le collecteur ne publie plus, ces
routes répondent 503 avec un message explicite, et NON 200 avec une liste
vide. La distinction est vitale : un mur d'alertes vide se lit « tout va
bien », alors que la réalité est « on ne voit plus rien ». Le pire état d'un
NOC est celui où il ne sait pas qu'il est aveugle.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from app.core.config import METRIC_TYPES, NODE_STATES, SEVERITIES
from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models import User
from app.services import (
    alerts_service,
    history_service,
    interop_service,
    kpi_service,
    live_service,
    metrics_service,
    node_service,
)

router = APIRouter(prefix="/api", tags=["état courant"])


def _one_of(values) -> str:
    """Motif d'énumération ANCRÉ : sans ^…$, pydantic accepte toute chaîne
    qui CONTIENT une valeur permise."""
    return "^(" + "|".join(values) + ")$"


_PERIOD_PATTERN = r"^(1h|6h|24h|7d|30d|90d|1y)$"

# Clé d'alerte ou d'équipement en chemin (`zabbix:1042`).
ResourceKey = Annotated[str, Path(min_length=1, max_length=300)]


def _unavailable(exc: live_service.SnapshotUnavailable) -> HTTPException:
    """503 et non 500 : ce n'est pas un défaut du backend mais une chaîne de
    collecte interrompue, et le message doit dire quoi regarder."""
    return HTTPException(
        status_code=503,
        detail={
            "error": "snapshot_unavailable",
            "message": (
                "Aucun instantané récent : le collecteur ne publie plus. "
                "Vérifier le conteneur `collector` et l'écran Interopérabilité."
            ),
            "detail": exc.detail,
        },
    )


# ---------------------------------------------------------------------------
# Synthèses
# ---------------------------------------------------------------------------
@router.get("/overview")
async def overview(current_user: User = Depends(get_current_user)):
    """Tuiles du haut de page : le parc, les alertes, la fraîcheur."""
    try:
        return await kpi_service.live_summary()
    except live_service.SnapshotUnavailable as exc:
        raise _unavailable(exc) from exc


@router.get("/sites")
async def sites(current_user: User = Depends(get_current_user)):
    """Synthèse par site, du plus dégradé au plus sain."""
    try:
        return await live_service.sites_summary()
    except live_service.SnapshotUnavailable as exc:
        raise _unavailable(exc) from exc


@router.get("/alerts/by-severity")
async def alerts_by_severity(current_user: User = Depends(get_current_user)):
    try:
        return await kpi_service.alerts_by_severity()
    except live_service.SnapshotUnavailable as exc:
        raise _unavailable(exc) from exc


@router.get("/alerts/by-tool")
async def alerts_by_tool(current_user: User = Depends(get_current_user)):
    try:
        return await kpi_service.alerts_by_tool()
    except live_service.SnapshotUnavailable as exc:
        raise _unavailable(exc) from exc


@router.get("/alerts/hour-distribution")
async def hour_distribution(current_user: User = Depends(get_current_user)):
    try:
        return await kpi_service.hour_distribution()
    except live_service.SnapshotUnavailable as exc:
        raise _unavailable(exc) from exc


# ---------------------------------------------------------------------------
# Alertes
# ---------------------------------------------------------------------------
@router.get("/alerts")
async def list_alerts(
    severity: str | None = Query(None, pattern=_one_of(SEVERITIES)),
    tool: str | None = Query(None, max_length=100),
    site: str | None = Query(None, max_length=150),
    acknowledged: bool | None = None,
    include_maintenance: bool = True,
    limit: int = Query(500, ge=1, le=5000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await alerts_service.list_alerts(
            db,
            severity=severity,
            tool=tool,
            site=site,
            acknowledged=acknowledged,
            include_maintenance=include_maintenance,
            limit=limit,
        )
    except live_service.SnapshotUnavailable as exc:
        raise _unavailable(exc) from exc


@router.get("/alerts/{alert_key:path}")
async def get_alert(
    alert_key: ResourceKey,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fiche d'une alerte.

    `:path` sur le paramètre parce qu'une clé d'alerte contient un
    deux-points (`zabbix:1042`) — sans lui, FastAPI n'accepterait que la
    partie avant le séparateur et la route serait introuvable.
    """
    try:
        alert = await alerts_service.get_alert(db, alert_key)
    except live_service.SnapshotUnavailable as exc:
        raise _unavailable(exc) from exc
    if alert is None:
        raise HTTPException(404, "Alerte inconnue.")
    return alert


# ---------------------------------------------------------------------------
# Équipements
# ---------------------------------------------------------------------------
@router.get("/nodes")
async def list_nodes(
    state: str | None = Query(None, pattern=_one_of(NODE_STATES)),
    site: str | None = Query(None, max_length=150),
    tool: str | None = Query(None, max_length=100),
    search: str | None = Query(None, max_length=200),
    sort: str = Query("state", pattern=r"^(state|name|site|alerts|tools)$"),
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await node_service.list_nodes(
            db, state=state, site=site, tool=tool, search=search,
            sort=sort, limit=limit, offset=offset,
        )
    except live_service.SnapshotUnavailable as exc:
        raise _unavailable(exc) from exc


@router.get("/nodes/states")
async def node_states(current_user: User = Depends(get_current_user)):
    try:
        return await node_service.state_counts()
    except live_service.SnapshotUnavailable as exc:
        raise _unavailable(exc) from exc


@router.get("/nodes/coverage")
async def node_coverage(current_user: User = Depends(get_current_user)):
    """Couverture par outil, et nombre d'équipements vus par un seul.

    Ce dernier chiffre est le plus utile : un équipement vu par un seul
    outil est un point de rupture — si cet outil tombe, on le perd de vue
    sans que rien ne le signale.
    """
    try:
        return await node_service.coverage_by_tool()
    except live_service.SnapshotUnavailable as exc:
        raise _unavailable(exc) from exc


@router.get("/nodes/{node_id:path}/metrics")
async def node_metrics(
    node_id: ResourceKey,
    metric: str | None = Query(None, pattern=_one_of(METRIC_TYPES)),
    period: str = Query("24h", pattern=_PERIOD_PATTERN),
    current_user: User = Depends(get_current_user),
):
    """Courbes d'un équipement — INTERROGE L'OUTIL SOURCE.

    C'est la seule famille de routes qui sorte du cache : elle demande la
    série à Zabbix ou Centreon, puis la met en cache Redis pour que les
    consultations suivantes ne repartent pas vers la production. Ne jamais
    la placer sur un écran qui se rafraîchit tout seul.
    """
    try:
        if metric:
            return await metrics_service.node_series(node_id, metric, period)
        return await metrics_service.node_all_series(node_id, period)
    except live_service.SnapshotUnavailable as exc:
        raise _unavailable(exc) from exc
    except history_service.HistoryUnavailable as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error": "source_unavailable",
                "tool": exc.tool,
                "message": (
                    f"L'outil {exc.tool} n'a pas répondu : {exc.detail}. "
                    "L'historique est lu chez l'outil source, il n'est pas "
                    "recopié dans le NOC."
                ),
            },
        ) from exc


@router.get("/nodes/{node_id:path}")
async def get_node(
    node_id: ResourceKey,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        node = await node_service.get_node(db, node_id)
    except live_service.SnapshotUnavailable as exc:
        raise _unavailable(exc) from exc
    if node is None:
        raise HTTPException(404, "Équipement inconnu de l'instantané courant.")
    return node


# ---------------------------------------------------------------------------
# Réseau
# ---------------------------------------------------------------------------
@router.get("/network/snapshot")
async def network_snapshot(current_user: User = Depends(get_current_user)):
    try:
        return await metrics_service.network_snapshot()
    except live_service.SnapshotUnavailable as exc:
        raise _unavailable(exc) from exc


@router.get("/network/down")
async def network_down(current_user: User = Depends(get_current_user)):
    try:
        return await metrics_service.nodes_down()
    except live_service.SnapshotUnavailable as exc:
        raise _unavailable(exc) from exc


@router.get("/network/top")
async def network_top(
    limit: int = Query(10, ge=1, le=100),
    current_user: User = Depends(get_current_user),
):
    try:
        return await metrics_service.top_nodes(limit)
    except live_service.SnapshotUnavailable as exc:
        raise _unavailable(exc) from exc


@router.get("/network/series")
async def network_series(
    metric: str = Query("latency_ms", pattern=_one_of(METRIC_TYPES)),
    period: str = Query("24h", pattern=_PERIOD_PATTERN),
    sample: int = Query(12, ge=1, le=50),
    current_user: User = Depends(get_current_user),
):
    """Courbe agrégée du réseau, sur un ÉCHANTILLON d'équipements.

    Le paramètre `sample` est plafonné volontairement : interroger tout le
    parc produirait autant d'appels vers les outils sources qu'il y a
    d'équipements, ce que cette architecture existe précisément pour éviter.
    La réponse indique sur combien d'équipements la courbe porte.
    """
    try:
        return await metrics_service.network_series(metric, period, sample)
    except live_service.SnapshotUnavailable as exc:
        raise _unavailable(exc) from exc


# ---------------------------------------------------------------------------
# Interopérabilité
# ---------------------------------------------------------------------------
@router.get("/interop/status")
async def interop_status(current_user: User = Depends(get_current_user)):
    """État de la chaîne de collecte. Reste servi même quand tout le reste
    ne l'est plus — c'est précisément à ce moment qu'on en a besoin."""
    return await interop_service.status()


@router.get("/interop/merge")
async def interop_merge(current_user: User = Depends(get_current_user)):
    return await interop_service.merge_report()
