from app.routes.alerts import router as alerts_router
from app.routes.auth import router as auth_router
from app.routes.incidents import router as incidents_router
from app.routes.kpi import locality_router, router as kpi_router
from app.routes.notifications import router as notifications_router
from app.routes.report import router as report_router
from app.routes.sla import router as sla_router
from app.routes.ws import router as ws_router

all_routers = [
    auth_router,
    kpi_router,
    locality_router,
    sla_router,
    alerts_router,
    incidents_router,
    report_router,
    ws_router,
    notifications_router,
]
