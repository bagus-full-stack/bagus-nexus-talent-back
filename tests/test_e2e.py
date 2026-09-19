"""Un test de bout en bout par parcours critique. Les services externes (LLM, GliNER,
Qdrant, Neo4j, Celery) sont mockés : ces tests vérifient l'orchestration de l'application,
pas la disponibilité de services tiers."""

import uuid
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.neo4j import get_neo4j_session
from app.db.qdrant import get_qdrant_client
from app.main import app
from app.models.cv import CV, CVStatus
from app.models.user import UserRole
from app.schemas.candidat import CandidatCV, Competence
from app.schemas.search import CandidatRecommande, FiltresRecherche, SearchResponse, SyntheseRecherche
from app.services.ingestion_service import run_pipeline
from app.services.search_service import TOP_K_LLM_HARD_CAP


# ---- 1. Upload d'un CV -> statut "ok" ou "a_valider" après pipeline (LLM/GliNER mockés) ----

@pytest.mark.asyncio
async def test_e2e_cv_upload_reaches_ok_or_a_valider(
    client: AsyncClient, db_session: AsyncSession, login_as, monkeypatch
):
    from app.tasks.ingestion_tasks import process_cv_task, trigger_indexing

    # Le worker Celery est hors scope d'un test d'intégration HTTP : on simule son
    # déclenchement synchrone plus bas, une fois l'upload confirmé en base.
    monkeypatch.setattr(process_cv_task, "delay", lambda cv_id: None)
    monkeypatch.setattr(trigger_indexing, "delay", lambda cv_id: None)

    _, headers = await login_as(UserRole.RH_INTERNE)

    response = await client.post(
        "/api/v1/ingestion/upload",
        files={"files": ("cv.pdf", b"%PDF-1.4 contenu factice", "application/pdf")},
        headers=headers,
    )
    assert response.status_code == 201
    cv_id = uuid.UUID(response.json()[0]["id"])

    cv = await db_session.get(CV, cv_id)
    assert cv is not None
    assert cv.statut == CVStatus.EN_COURS

    monkeypatch.setattr("app.services.ingestion_service.extract_text", lambda path: "Jean Dupont " * 30)
    monkeypatch.setattr("app.services.ingestion_service.detect_language", lambda text: "fr")
    monkeypatch.setattr("app.services.ingestion_service.extract_entities", lambda text: [])
    monkeypatch.setattr(
        "app.services.ingestion_service.structure_with_llm",
        lambda text, entities: (
            CandidatCV(
                nom="Dupont",
                prenom="Jean",
                email="jean.dupont@example.com",
                competences=[Competence(nom="Python")],
                source_confiance={"nom": 0.9, "prenom": 0.9, "email": 0.9, "experiences": 0.9},
            ),
            {"prompt_tokens": 10, "completion_tokens": 10},
        ),
    )

    await run_pipeline(db_session, cv_id)

    await db_session.refresh(cv)
    assert cv.statut in (CVStatus.OK, CVStatus.A_VALIDER)
    assert cv.donnees_json is not None


# ---- 2. Recherche simple -> schéma respecté et candidats <= TOP_K_LLM ----------------

@pytest.mark.asyncio
async def test_e2e_search_respects_schema_and_top_k_cap(
    client: AsyncClient, db_session: AsyncSession, login_as, monkeypatch
):
    _, headers = await login_as(UserRole.RECRUTEUR)

    cv = CV(
        id=uuid.uuid4(),
        nom_fichier="cv.pdf",
        storage_path="x",
        statut=CVStatus.OK,
        donnees_json=CandidatCV(
            nom="Dupont", prenom="Jean", competences=[Competence(nom="Python")]
        ).model_dump(mode="json"),
    )
    db_session.add(cv)
    await db_session.commit()

    monkeypatch.setattr(
        "app.services.search_service.extract_filters", lambda query: (FiltresRecherche(), query)
    )
    monkeypatch.setattr("app.services.search_service.get_embedding", lambda text: [0.0] * 1536)

    class FakeQdrant:
        async def search(self, **kwargs):
            return [SimpleNamespace(payload={"id_candidat": str(cv.id)}, score=0.9)]

    class FakeNeo4jResult:
        def __aiter__(self):
            return self._gen()

        async def _gen(self):
            return
            yield  # pragma: no cover

    class FakeNeo4jSession:
        async def run(self, query, **kwargs):
            return FakeNeo4jResult()

    async def fake_synthesize(query: str, context: list[dict]) -> SyntheseRecherche:
        return SyntheseRecherche(
            candidats_recommandes=[
                CandidatRecommande(candidat_id=str(cv.id), justification="Python confirmé", score=0.9)
            ],
            resume_synthese="Un candidat Python correspond à la requête.",
        )

    monkeypatch.setattr("app.services.search_service._synthesize_with_llm", fake_synthesize)

    async def _fake_neo4j_session():
        yield FakeNeo4jSession()

    app.dependency_overrides[get_qdrant_client] = lambda: FakeQdrant()
    app.dependency_overrides[get_neo4j_session] = _fake_neo4j_session
    try:
        response = await client.post(
            "/api/v1/candidats/search", json={"query": "développeur python"}, headers=headers
        )
    finally:
        del app.dependency_overrides[get_qdrant_client]
        del app.dependency_overrides[get_neo4j_session]

    assert response.status_code == 200
    body = SearchResponse.model_validate(response.json())
    assert len(body.candidats) <= TOP_K_LLM_HARD_CAP
    assert body.candidats[0].candidat_id == str(cv.id)


# ---- 3. Demande RGPD : création puis exécution -> état final et rapport ----------------

@pytest.mark.asyncio
async def test_e2e_gdpr_request_create_then_execute(
    client: AsyncClient, db_session: AsyncSession, login_as, monkeypatch
):
    admin, headers = await login_as(UserRole.ADMIN)
    cv = CV(id=uuid.uuid4(), nom_fichier="cv.pdf", storage_path="x", statut=CVStatus.OK)
    db_session.add(cv)
    await db_session.commit()

    class FakeQdrant:
        async def count(self, **kwargs):
            return SimpleNamespace(count=0)

        async def delete(self, **kwargs):
            return None

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

    class FakeNeo4jSession:
        async def run(self, query, **params):
            if query == "MATCH (c:Candidat {id: $id})-[r]-() RETURN count(r) AS total":
                return FakeSingleResult({"total": 0})
            if query == "MATCH (c:Candidat {id: $id}) DETACH DELETE c":
                return FakeEmptyResult()
            raise NotImplementedError(query)

    async def _fake_neo4j_session():
        yield FakeNeo4jSession()

    app.dependency_overrides[get_qdrant_client] = lambda: FakeQdrant()
    app.dependency_overrides[get_neo4j_session] = _fake_neo4j_session
    try:
        create_response = await client.post(
            "/api/v1/gdpr/",
            json={"candidat_id": str(cv.id), "type": "suppression"},
            headers=headers,
        )
        assert create_response.status_code == 201
        request_id = create_response.json()["id"]

        execute_response = await client.post(
            f"/api/v1/gdpr/{request_id}/execute",
            json={"password": "Passw0rd!"},
            headers=headers,
        )
    finally:
        del app.dependency_overrides[get_qdrant_client]
        del app.dependency_overrides[get_neo4j_session]

    assert execute_response.status_code == 200
    body = execute_response.json()
    assert body["statut"] == "terminee"
    assert set(body["resultat_json"].keys()) == {"relations_supprimees", "vecteurs_supprimes", "hash_audit"}
    assert body["resultat_json"]["relations_supprimees"] == 0
    assert body["resultat_json"]["vecteurs_supprimes"] == 0


# ---- 4. Un recruteur ne peut pas accéder à /api/v1/ingestion ---------------------------

@pytest.mark.asyncio
async def test_e2e_recruteur_forbidden_on_ingestion(client: AsyncClient, login_as):
    _, headers = await login_as(UserRole.RECRUTEUR)

    response = await client.get("/api/v1/ingestion/", headers=headers)

    assert response.status_code == 403
