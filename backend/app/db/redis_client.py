"""Client Redis partagé avec l'ETL (même REDIS_URL, voir core/config.py)."""
import redis

from app.core.config import REDIS_URL

redis_client = redis.from_url(
    REDIS_URL, decode_responses=True, socket_connect_timeout=2, socket_timeout=2
)
