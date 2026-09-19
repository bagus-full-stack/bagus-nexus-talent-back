import uuid

import pytest

from app.models.cv import CV
from app.schemas.candidat import CandidatCV, Competence, Diplome
from app.schemas.search import CandidatRecommande, SyntheseRecherche
from app.services.search_service import TOP_K_LLM_HARD_CAP, _rerank, _synthesize_with_llm, build_candidat_detail


# ---- TOP_K_LLM respecté même avec un pool plus large -------------------------

def test_rerank_slices_to_requested_top_k():
    hits = [{"candidat_id": f"c{i}", "score": i / 100} for i in range(20)]

    ranked = _rerank(hits, top_k=8)

    assert len(ranked) == 8
    assert [h["candidat_id"] for h in ranked] == [f"c{i}" for i in range(19, 11, -1)]


def test_top_k_llm_hard_cap_enforced_even_if_admin_config_requests_more():
    hits = [{"candidat_id": f"c{i}", "score": i / 100} for i in range(20)]

    top_k = min(100, TOP_K_LLM_HARD_CAP)  # admin config asked for 100
    ranked = _rerank(hits, top_k=top_k)

    assert TOP_K_LLM_HARD_CAP == 15
    assert len(ranked) == 15


# ---- Anonymisation ------------------------------------------------------------

def test_anonymisation_masks_identity_fields_but_keeps_competences():
    cv = CV(id=uuid.uuid4(), nom_fichier="cv.pdf", storage_path="x")
    candidat = CandidatCV(
        nom="Dupont",
        prenom="Jean",
        email="jean@example.com",
        telephone="0601020304",
        localisation="Paris",
        competences=[Competence(nom="Python")],
        diplomes=[Diplome(intitule="Master Informatique")],
        annees_experience_cumulees=5.0,
        statut_qualite="ok",
    )

    detail = build_candidat_detail(cv, candidat, anonymise=True)

    assert detail.nom == f"Candidat #{str(cv.id)[:8]}"
    assert detail.prenom is None
    assert detail.email is None
    assert detail.telephone is None
    assert detail.competences == candidat.competences
    assert detail.diplomes == candidat.diplomes
    assert detail.annees_experience_cumulees == 5.0


# ---- Synthèse LLM (mock) respecte le schéma Pydantic -------------------------

@pytest.mark.asyncio
async def test_synthesize_with_llm_output_validated_against_schema(monkeypatch):
    fake_payload = SyntheseRecherche(
        candidats_recommandes=[
            CandidatRecommande(
                candidat_id="abc123",
                justification="5 ans d'expérience Python confirmés dans le CV",
                elements_cites=["5 ans d'expérience en Python"],
                score=0.9,
            )
        ],
        resume_synthese="Un candidat correspond bien à la requête.",
    )

    def fake_generate_structured(contents, response_schema, system_instruction=None):
        return fake_payload, {"model": "fake", "prompt_tokens": 1, "completion_tokens": 1}

    import app.core.llm

    monkeypatch.setattr(app.core.llm, "generate_structured", fake_generate_structured)

    result = await _synthesize_with_llm("candidats Python", [{"candidat_id": "abc123"}])

    assert isinstance(result, SyntheseRecherche)
    assert result.resume_synthese == fake_payload.resume_synthese
    assert result.candidats_recommandes[0].candidat_id == "abc123"
