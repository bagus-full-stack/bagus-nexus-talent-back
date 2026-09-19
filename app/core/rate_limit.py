from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

# Redis-backed: the API runs with multiple uvicorn workers (see Dockerfile), so
# in-memory storage would let each worker keep its own counter and undercount abuse.
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.REDIS_URL,
    default_limits=["200/minute"],
    enabled=settings.RATE_LIMIT_ENABLED,
)
