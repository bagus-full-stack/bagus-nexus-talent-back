from redis.asyncio import Redis

from app.core.config import settings

_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)


def get_redis_client() -> Redis:
    return _client
