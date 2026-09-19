import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.config import settings as app_settings
from app.core.rate_limit import limiter
from app.db.neo4j import driver as neo4j_driver
from app.db.qdrant import get_qdrant_client
from app.routers import auth, candidats, gdpr, graph, health, ingestion, notifications, settings, users
from app.services.graph_service import ensure_collections, ensure_constraints

logger = logging.getLogger("startup")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await ensure_collections(get_qdrant_client())
    except Exception:
        logger.warning("Could not ensure Qdrant collections at startup", exc_info=True)

    try:
        async with neo4j_driver.session() as session:
            await ensure_constraints(session)
    except Exception:
        logger.warning("Could not ensure Neo4j constraints at startup", exc_info=True)

    yield


app = FastAPI(title="NexusTalent API", lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=app_settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for _router in (
    health.router,
    auth.router,
    users.router,
    candidats.router,
    ingestion.router,
    graph.router,
    gdpr.router,
    settings.router,
    notifications.router,
):
    app.include_router(_router)
