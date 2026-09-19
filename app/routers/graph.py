from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.dependencies import require_role
from app.db.neo4j import get_neo4j_session
from app.models.user import UserRole
from app.schemas.graph import SubgraphResponse
from app.services.graph_service import get_node_detail, get_subgraph

router = APIRouter(
    prefix="/api/v1/graph",
    tags=["graph"],
    dependencies=[Depends(require_role(UserRole.RH_INTERNE, UserRole.ADMIN))],
)


@router.get("/subgraph", response_model=SubgraphResponse)
async def subgraph(
    types: list[str] = Query(default=[]),
    depth: int = 2,
    search: str | None = None,
    neo4j_session=Depends(get_neo4j_session),
):
    return await get_subgraph(neo4j_session, types, depth, search)


@router.get("/node/{node_id}")
async def node_detail(node_id: str, neo4j_session=Depends(get_neo4j_session)):
    detail = await get_node_detail(neo4j_session, node_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nœud introuvable")
    return detail
