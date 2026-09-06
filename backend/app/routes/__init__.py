from app.routes.alerts import router as alerts_router
from app.routes.assets import router as assets_router
from app.routes.auth import router as auth_router
from app.routes.field import router as field_router
from app.routes.health import router as health_router
from app.routes.incidents import router as incidents_router
from app.routes.interop import router as interop_router
from app.routes.kpi import locality_router, router as kpi_router
from app.routes.maintenance import router as maintenance_router
from app.routes.metrics import router as metrics_router
from app.routes.notifications import router as notifications_router
from app.routes.report import router as report_router
from app.routes.sla import router as sla_router
from app.routes.users import router as users_router
from app.routes.ws import router as ws_router

all_routers = [
    health_router,
    auth_router,
    users_router,
    kpi_router,
    locality_router,
    sla_router,
    alerts_router,
    incidents_router,
    field_router,
    report_router,
    ws_router,
    notifications_router,
    interop_router,
    metrics_router,
    assets_router,
    maintenance_router,
]