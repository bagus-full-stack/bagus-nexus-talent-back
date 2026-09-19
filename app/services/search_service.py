import json
import logging
import time

from qdrant_client import AsyncQdrantClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.embeddings import get_embedding
from app.models.app_settings import ParametresGlobaux
from app.models.cv import CV, CVStatus
from app.schemas.candidat import CandidatCV
from app.schemas.search import CandidatDetailResponse, FiltresRecherche, SyntheseRecherche
from app.services.graph_service import CV_CHUNKS_COLLECTION

logger = logging.getLogger("search")

TOP_K_LLM_HARD_CAP = 15
VECTOR_POOL_TOP_K = 20
COMPOSITE_WEIGHT_VECTOR = 0.7
COMPOSITE_WEIGHT_FILTRE = 0.3


class _FiltresExtraction(FiltresRecherche):
    requete_residuelle: str


# ---- Self-querying : extraction des filtres stricts -------------------------

def extract_filters(query: str) -> tuple[FiltresRecherche, str]:
    """Calls Gemini (structured output) to split the query into strict FiltresRecherche
    plus the residual free-text part destined to vector search. Falls back to an
    empty filter set (unfiltered query) on any LLM/validation failure."""
    try:
        from app.core.llm import generate_structured

        system_instruction = (
            "Tu extrais les filtres stricts d'une requête de recherche de candidats "
            "(expérience minimale, compétences requises, diplôme minimal, langues, "
            "localisation, disponibilité). Renvoie aussi `requete_residuelle` : la "
            "requête débarrassée de ces critères, destinée à une recherche sémantique."
        )
        extraction, _usage = generate_structured(query, _FiltresExtraction, system_instruction)
        filtres = FiltresRecherche(**extraction.model_dump(exclude={"requete_residuelle"}))
        return filtres, extraction.requete_residuelle
    except Exception:
        logger.warning("extract_filters failed, falling back to unfiltered query", exc_info=True)
        return FiltresRecherche(), query


# ---- Étape 1 : filtrage SQL/JSON strict --------------------------------------

def _matches_filters(candidat: CandidatCV, filtres: FiltresRecherche) -> bool:
    if filtres.experience_min_annees is not None:
        if (candidat.annees_experience_cumulees or 0) < filtres.experience_min_annees:
            return False

    if filtres.competences_requises:
        candidat_competences = {c.nom.lower() for c in candidat.competences}
        if not all(req.lower() in candidat_competences for req in filtres.competences_requises):
            return False

    if filtres.diplome_min:
        diplomes = " ".join(d.intitule.lower() for d in candidat.diplomes)
        if filtres.diplome_min.lower() not in diplomes:
            return False

    if filtres.langues_requises:
        langue = (candidat.langue_detectee or "").lower()
        if not any(langue_requise.lower() in langue for langue_requise in filtres.langues_requises):
            return False

    if filtres.localisation:
        if filtres.localisation.lower() not in (candidat.localisation or "").lower():
            return False

    if filtres.disponibilite_avant:
        if candidat.disponible_a_partir_de and candidat.disponible_a_partir_de > filtres.disponibilite_avant:
            return False

    return True


async def _sql_filter_pool(db: AsyncSession, filtres: FiltresRecherche) -> list[tuple[CV, CandidatCV]]:
    result = await db.execute(select(CV).where(CV.statut == CVStatus.OK, CV.donnees_json.is_not(None)))
    pool = []
    for cv in result.scalars().all():
        candidat = CandidatCV.model_validate(cv.donnees_json)
        if _matches_filters(candidat, filtres):
            pool.append((cv, candidat))
    return pool


# ---- Étape 2 : recherche vectorielle sur le pool filtré ----------------------

async def _vector_search(
    qdrant: AsyncQdrantClient, residual_query: str, pool_ids: list[str], top_k: int = VECTOR_POOL_TOP_K
) -> list[dict]:
    if not pool_ids:
        return []

    from qdrant_client.models import FieldCondition, Filter, MatchAny

    embedding = get_embedding(residual_query.strip() or " ")
    hits = await qdrant.search(
        collection_name=CV_CHUNKS_COLLECTION,
        query_vector=embedding,
        query_filter=Filter(must=[FieldCondition(key="id_candidat", match=MatchAny(any=pool_ids))]),
        limit=top_k * 5,
    )

    best_by_candidat: dict[str, float] = {}
    for hit in hits:
        candidat_id = hit.payload["id_candidat"]
        if candidat_id not in best_by_candidat or hit.score > best_by_candidat[candidat_id]:
            best_by_candidat[candidat_id] = hit.score

    ranked = sorted(best_by_candidat.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    return [{"candidat_id": candidat_id, "score": score} for candidat_id, score in ranked]


# ---- Étape 3 : enrichissement graphe (batché) --------------------------------

async def _enrich_graph(neo4j_session, candidat_ids: list[str]) -> dict[str, dict]:
    if not candidat_ids:
        return {}

    result = await neo4j_session.run(
        "MATCH (c:Candidat) WHERE c.id IN $ids "
        "OPTIONAL MATCH (c)-[:POSSEDE]->(comp:Competence) "
        "OPTIONAL MATCH (c)-[:A_TRAVAILLE_CHEZ]->(ent:Entreprise) "
        "RETURN c.id AS id, collect(DISTINCT comp.libelle) AS competences, "
        "collect(DISTINCT ent.libelle) AS entreprises",
        ids=candidat_ids,
    )

    enrichment: dict[str, dict] = {}
    async for record in result:
        enrichment[record["id"]] = {
            "competences": [c for c in record["competences"] if c],
            "entreprises": [e for e in record["entreprises"] if e],
        }
    return enrichment


# ---- Étape 4 : re-ranking (score composite) ----------------------------------

def _rerank(vector_hits: list[dict], top_k: int) -> list[dict]:
    """Composite score: weighted vector similarity + filter-match score. The filter-match
    term is always 1.0 here since vector_hits already come from a strictly pre-filtered pool."""
    scored = [
        {**hit, "composite_score": COMPOSITE_WEIGHT_VECTOR * hit["score"] + COMPOSITE_WEIGHT_FILTRE * 1.0}
        for hit in vector_hits
    ]
    scored.sort(key=lambda h: h["composite_score"], reverse=True)
    return scored[:top_k]


# ---- Étape 5 : synthèse LLM (Claude 3.5 Sonnet) ------------------------------

def _build_llm_context(ranked: list[dict], pool_by_id: dict[str, CandidatCV], graph_data: dict) -> list[dict]:
    context = []
    for hit in ranked:
        candidat_id = hit["candidat_id"]
        candidat = pool_by_id.get(candidat_id)
        if candidat is None:
            continue
        enrichment = graph_data.get(candidat_id, {})
        context.append(
            {
                "candidat_id": candidat_id,
                "nom": candidat.nom,
                "prenom": candidat.prenom,
                "annees_experience": candidat.annees_experience_cumulees,
                "competences": [c.nom for c in candidat.competences] + enrichment.get("competences", []),
                "diplomes": [d.intitule for d in candidat.diplomes],
                "experiences": [
                    f"{e.poste} chez {e.entreprise or 'N/A'} ({e.date_debut} - {e.date_fin or 'présent'})"
                    for e in candidat.experiences
                ],
                "entreprises_graphe": enrichment.get("entreprises", []),
            }
        )
    return context


async def _synthesize_with_llm(query: str, context: list[dict]) -> SyntheseRecherche:
    from app.core.llm import generate_structured

    system_instruction = (
        "Tu es un assistant de recrutement. À partir des CV fournis en contexte, recommande les "
        "candidats les plus pertinents pour la requête. Pour chaque candidat recommandé, cite "
        "explicitement dans `elements_cites` les passages ou informations du CV qui justifient ton "
        "choix. N'invente JAMAIS d'information absente des CV fournis : si une information manque, "
        "ne l'affirme pas."
    )
    prompt = (
        f"Requête : {query}\n\nCandidats (JSON) :\n{json.dumps(context, ensure_ascii=False, default=str)}"
    )

    synthese, _usage = generate_structured(prompt, SyntheseRecherche, system_instruction)
    return synthese


# ---- Paramètres globaux (singleton) ------------------------------------------

async def get_parametres_globaux(db: AsyncSession) -> ParametresGlobaux:
    result = await db.execute(select(ParametresGlobaux))
    parametres = result.scalars().first()
    if parametres is None:
        parametres = ParametresGlobaux()
        db.add(parametres)
        await db.commit()
        await db.refresh(parametres)
    return parametres


# ---- Orchestration : pipeline de recherche hybride ---------------------------

async def hybrid_search(db: AsyncSession, qdrant: AsyncQdrantClient, neo4j_session, query: str) -> dict:
    timings: dict[str, float] = {}

    t0 = time.perf_counter()
    filtres, residual_query = extract_filters(query)
    timings["filtrage_extraction_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    t0 = time.perf_counter()
    pool = await _sql_filter_pool(db, filtres)
    timings["filtrage_sql_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    pool_by_id = {str(cv.id): candidat for cv, candidat in pool}
    pool_ids = list(pool_by_id.keys())

    t0 = time.perf_counter()
    vector_hits = await _vector_search(qdrant, residual_query, pool_ids, top_k=VECTOR_POOL_TOP_K)
    timings["vectoriel_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    t0 = time.perf_counter()
    graph_data = await _enrich_graph(neo4j_session, [hit["candidat_id"] for hit in vector_hits])
    timings["graphe_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    parametres = await get_parametres_globaux(db)
    top_k_llm = min(parametres.top_k_llm, TOP_K_LLM_HARD_CAP)
    ranked = _rerank(vector_hits, top_k_llm)
    context = _build_llm_context(ranked, pool_by_id, graph_data)

    t0 = time.perf_counter()
    synthese = await _synthesize_with_llm(query, context)
    timings["llm_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    logger.info(
        json.dumps({"event": "hybrid_search_timing", **timings, "total_ms": round(sum(timings.values()), 1)})
    )

    return {
        "filtres_extraits": filtres,
        "candidats": synthese.candidats_recommandes,
        "synthese": synthese.resume_synthese,
    }


# ---- Détail candidat (avec anonymisation) ------------------------------------

def build_candidat_detail(cv: CV, candidat: CandidatCV, anonymise: bool) -> CandidatDetailResponse:
    nom = candidat.nom
    prenom = candidat.prenom
    email = candidat.email
    telephone = candidat.telephone
    if anonymise:
        nom = f"Candidat #{str(cv.id)[:8]}"
        prenom = None
        email = None
        telephone = None

    return CandidatDetailResponse(
        id=str(cv.id),
        nom=nom,
        prenom=prenom,
        email=email,
        telephone=telephone,
        localisation=candidat.localisation,
        competences=candidat.competences,
        diplomes=candidat.diplomes,
        experiences=candidat.experiences,
        annees_experience_cumulees=candidat.annees_experience_cumulees,
        statut_qualite=candidat.statut_qualite,
    )
