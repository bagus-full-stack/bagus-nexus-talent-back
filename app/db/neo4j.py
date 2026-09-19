from collections.abc import AsyncGenerator

from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncSession

from app.core.config import settings

driver: AsyncDriver = AsyncGraphDatabase.driver(
    settings.NEO4J_URI, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
)


async def get_neo4j_session() -> AsyncGenerator[AsyncSession, None]:
    async with driver.session() as session:
        yield session
