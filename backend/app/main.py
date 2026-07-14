import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.constants import CACHE_TTL, CORS_ORIGINS, LOG_LEVEL
from app.routes import all_routers

# Without this, the root logger sits at WARNING with no handler, so every
# app-level logger.info/error call (notification_service, push_service, ...)
# is silently dropped — only uvicorn's own access logs show up.
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="NOC Dashboard API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in all_routers:
    app.include_router(router)


@app.get("/")
def read_root():
    return {"message": "NOC Dashboard API is running", "cache_ttl": CACHE_TTL}
