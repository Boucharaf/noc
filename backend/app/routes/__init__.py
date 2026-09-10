"""
Enregistrement des routeurs.

REGROUPEMENT PAR NATURE D'ACCÈS, et non par écran. C'est le changement
structurel de cette version : les anciens modules suivaient les pages du
tableau de bord (kpi, nodes, incidents, metrics, geo, coverage…), si bien
qu'une même donnée était servie par trois routes écrites à trois endroits,
avec trois façons de traiter l'absence de données.

Il n'y a plus que deux natures d'accès, et elles ont des propriétés très
différentes qu'il faut pouvoir distinguer d'un coup d'œil :

  live.py        LECTURE de l'instantané Redis. Quelques microsecondes,
                 aucune écriture, aucun appel sortant. C'est ce qui alimente
                 tous les écrans qui se rafraîchissent tout seuls.
                 (Une exception assumée : /nodes/{id}/metrics interroge
                 l'outil source, et son en-tête le dit.)

  operations.py  ÉCRITURE dans PostgreSQL, et lecture des agrégats
                 journaliers. Acquittements, causes, maintenances,
                 engagements de service.

Les autres modules restent séparés parce qu'ils ont chacun une contrainte
propre : authentification, chargement de fichiers, WebSocket, PDF.
"""
from app.routes.auth import router as auth_router
from app.routes.field import router as field_router
from app.routes.health import router as health_router
from app.routes.live import router as live_router
from app.routes.notifications import router as notifications_router
from app.routes.operations import router as operations_router
from app.routes.report import router as report_router
from app.routes.users import router as users_router
from app.routes.ws import router as ws_router

all_routers = [
    health_router,
    auth_router,
    users_router,
    live_router,
    operations_router,
    field_router,
    report_router,
    notifications_router,
    ws_router,
]
