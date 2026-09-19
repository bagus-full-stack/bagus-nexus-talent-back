from qdrant_client import AsyncQdrantClient

from app.core.config import settings

_client = AsyncQdrantClient(url=settings.QDRANT_URL)


def get_qdrant_client() -> AsyncQdrantClient:
    return _client
