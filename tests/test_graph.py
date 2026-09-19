import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.neo4j import get_neo4j_session
from app.main import app
from app.models.synonym import SynonymePaire
from app.models.user import User, UserRole
from app.services.graph_service import DEFAULT_SUBGRAPH_LIMIT, resolve_entity


# ---- Niveau 1 : synonymes ---------------------------------------------------

@pytest.mark.asyncio
async def test_reactjs_and_react_dot_js_resolve_to_same_label_via_synonyms(db_session: AsyncSession):
    db_session.add(SynonymePaire(terme_a="ReactJS", terme_b="React.js", type_entite="competence"))
    await db_session.commit()

    # qdrant=None proves level 2 is never reached: resolution stops at level 1 (synonym lookup).
    label_1 = await resolve_entity(db_session, None, "ReactJS", "competence")
    label_2 = await resolve_entity(db_session, None, "React.js", "competence")

    assert label_1 == label_2


# ---- Niveau 2 : nouvelle entité ---------------------------------------------

class FakeQdrantClient:
    def __init__(self):
        self.upserted = []

    async def search(self, **kwargs):
        return []  # no known label is close enough -> brand new entity

    async def upsert(self, **kwargs):
        self.upserted.append(kwargs)


@pytest.mark.asyncio
async def test_brand_new_competence_creates_new_entity(db_session: AsyncSession, monkeypatch):
    monkeypatch.setattr("app.services.graph_service.get_embedding", lambda text: [0.0] * 1536)
    qdrant = FakeQdrantClient()

    label = await resolve_entity(db_session, qdrant, "Rust Embarqué", "competence")

    assert label == "rust embarqué"
    assert len(qdrant.upserted) == 1
    assert qdrant.upserted[0]["points"][0].payload["libelle_normalise"] == "rust embarqué"


# ---- Limite dure du /subgraph ------------------------------------------------

class FakeNode(dict):
    def __init__(self, element_id, labels, **props):
        super().__init__(**props)
        self.element_id = element_id
        self.labels = labels


class FakeResult:
    def __init__(self, records):
        self._records = records

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for record in self._records:
            yield record


class FakeNeo4jSession:
    def __init__(self, results):
        self._results = list(results)

    async def run(self, query, **kwargs):
        return FakeResult(self._results.pop(0))


async def _create_admin(db: AsyncSession) -> None:
    db.add(
        User(
            email="admin-graph@example.com",
            nom="Admin",
            mot_de_passe_hash=hash_password("Passw0rd!"),
            role=UserRole.ADMIN,
        )
    )
    await db.commit()


@pytest.mark.asyncio
async def test_subgraph_respects_hard_node_limit(client: AsyncClient, db_session: AsyncSession):
    await _create_admin(db_session)
    login = await client.post(
        "/api/v1/auth/login", json={"email": "admin-graph@example.com", "password": "Passw0rd!"}
    )
    token = login.json()["access_token"]

    node_records = [{"n": FakeNode(f"n{i}", ["Competence"], libelle=f"skill{i}")} for i in range(DEFAULT_SUBGRAPH_LIMIT + 5)]
    fake_session = FakeNeo4jSession([node_records, []])

    async def _override():
        yield fake_session

    app.dependency_overrides[get_neo4j_session] = _override
    try:
        response = await client.get(
            "/api/v1/graph/subgraph", headers={"Authorization": f"Bearer {token}"}
        )
    finally:
        app.dependency_overrides.pop(get_neo4j_session, None)

    assert response.status_code == 200
    body = response.json()
    assert len(body["nodes"]) == DEFAULT_SUBGRAPH_LIMIT
    assert body["truncated"] is True
