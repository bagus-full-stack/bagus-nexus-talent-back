import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.cv import CV, CVStatus
from app.models.gdpr_request import GDPRRequest, GDPRRequestStatus, GDPRRequestType
from app.models.user import User, UserRole
from app.schemas.candidat import CandidatCV, Competence
from app.services.gdpr_service import supprimer_candidat
from app.services.graph_service import index_candidat_graph


# ---- Fakes : graphe en mémoire n'implémentant que les requêtes réellement émises ----

class FakeQdrantClient:
    def __init__(self):
        self.upserted = []
        self.deleted_filters = []

    async def search(self, **kwargs):
        return []  # force la création d'une nouvelle entité normalisée

    async def upsert(self, **kwargs):
        self.upserted.append(kwargs)

    async def count(self, **kwargs):
        class _Count:
            count = 0

        return _Count()

    async def delete(self, **kwargs):
        self.deleted_filters.append(kwargs)


class FakeSingleResult:
    def __init__(self, record):
        self._record = record

    async def single(self):
        return self._record


class FakeEmptyResult:
    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        return
        yield  # pragma: no cover


class FakeGraphDB:
    """Stand-in Neo4j session implementing only the exact Cypher shapes emitted by
    index_candidat_graph and supprimer_candidat, with real DETACH DELETE semantics:
    only the targeted node and its relations are removed, never other nodes."""

    def __init__(self):
        self.candidats: set[str] = set()
        self.competences: set[str] = set()
        self.possede: set[tuple[str, str]] = set()

    async def run(self, query, **params):
        if query.startswith("MERGE (c:Candidat {id: $id}) SET"):
            self.candidats.add(params["id"])
            return FakeEmptyResult()
        if "MERGE (comp:Competence" in query:
            self.competences.add(params["libelle"])
            self.possede.add((params["id"], params["libelle"]))
            return FakeEmptyResult()
        if query == "MATCH (c:Candidat {id: $id})-[r]-() RETURN count(r) AS total":
            total = sum(1 for cid, _ in self.possede if cid == params["id"])
            return FakeSingleResult({"total": total})
        if query == "MATCH (c:Candidat {id: $id}) DETACH DELETE c":
            self.candidats.discard(params["id"])
            self.possede = {(cid, lib) for cid, lib in self.possede if cid != params["id"]}
            return FakeEmptyResult()
        raise NotImplementedError(query)


# ---- Suppression : ne touche jamais les entités partagées --------------------

@pytest.mark.asyncio
async def test_supprimer_candidat_preserves_competence_shared_by_another_candidat(
    db_session: AsyncSession, monkeypatch
):
    monkeypatch.setattr("app.services.graph_service.get_embedding", lambda text: [0.0] * 1536)
    qdrant = FakeQdrantClient()
    graph = FakeGraphDB()

    candidat_1_id = str(uuid.uuid4())
    candidat_2_id = str(uuid.uuid4())
    db_session.add_all(
        [
            CV(id=uuid.UUID(candidat_1_id), nom_fichier="cv1.pdf", storage_path="x", statut=CVStatus.OK),
            CV(id=uuid.UUID(candidat_2_id), nom_fichier="cv2.pdf", storage_path="y", statut=CVStatus.OK),
        ]
    )
    await db_session.commit()

    candidat_1 = CandidatCV(nom="Dupont", competences=[Competence(nom="Python")])
    candidat_2 = CandidatCV(nom="Martin", competences=[Competence(nom="Python")])
    await index_candidat_graph(graph, db_session, qdrant, candidat_1_id, candidat_1)
    await index_candidat_graph(graph, db_session, qdrant, candidat_2_id, candidat_2)

    assert (candidat_1_id, "python") in graph.possede
    assert (candidat_2_id, "python") in graph.possede

    resultat = await supprimer_candidat(graph, qdrant, db_session, candidat_1_id)

    assert candidat_1_id not in graph.candidats
    assert candidat_2_id in graph.candidats
    assert "python" in graph.competences  # compétence partagée toujours présente
    assert (candidat_2_id, "python") in graph.possede
    assert resultat["relations_supprimees"] == 1
    assert await db_session.get(CV, uuid.UUID(candidat_1_id)) is None
    assert await db_session.get(CV, uuid.UUID(candidat_2_id)) is not None


# ---- Endpoint /execute : re-authentification et idempotence ------------------

async def _create_admin(db: AsyncSession, password: str = "Passw0rd!") -> User:
    admin = User(
        email="admin-gdpr@example.com", nom="Admin", mot_de_passe_hash=hash_password(password), role=UserRole.ADMIN
    )
    db.add(admin)
    await db.commit()
    await db.refresh(admin)
    return admin


async def _login(client: AsyncClient, email: str, password: str) -> str:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    return response.json()["access_token"]


@pytest.mark.asyncio
async def test_execute_wrong_password_returns_403_and_does_not_execute(client: AsyncClient, db_session: AsyncSession):
    admin = await _create_admin(db_session)
    cv = CV(id=uuid.uuid4(), nom_fichier="cv.pdf", storage_path="x", statut=CVStatus.OK)
    db_session.add(cv)
    demande = GDPRRequest(candidat_id=cv.id, type=GDPRRequestType.SUPPRESSION, demande_par=admin.id)
    db_session.add(demande)
    await db_session.commit()
    await db_session.refresh(demande)

    token = await _login(client, "admin-gdpr@example.com", "Passw0rd!")
    response = await client.post(
        f"/api/v1/gdpr/{demande.id}/execute",
        json={"password": "MauvaisMotDePasse!"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    await db_session.refresh(demande)
    assert demande.statut == GDPRRequestStatus.EN_ATTENTE
    assert await db_session.get(CV, cv.id) is not None


@pytest.mark.asyncio
async def test_execute_twice_returns_409(client: AsyncClient, db_session: AsyncSession):
    admin = await _create_admin(db_session)
    cv = CV(id=uuid.uuid4(), nom_fichier="cv.pdf", storage_path="x", statut=CVStatus.OK)
    db_session.add(cv)
    demande = GDPRRequest(
        candidat_id=cv.id,
        type=GDPRRequestType.ANONYMISATION,
        demande_par=admin.id,
        statut=GDPRRequestStatus.TERMINEE,
    )
    db_session.add(demande)
    await db_session.commit()
    await db_session.refresh(demande)

    token = await _login(client, "admin-gdpr@example.com", "Passw0rd!")
    response = await client.post(
        f"/api/v1/gdpr/{demande.id}/execute",
        json={"password": "Passw0rd!"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 409
