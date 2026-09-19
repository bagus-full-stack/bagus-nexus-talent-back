import re
import uuid

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.embeddings import EMBEDDING_DIMENSION, get_embedding
from app.models.synonym import SynonymePaire
from app.schemas.candidat import CandidatCV

CV_CHUNKS_COLLECTION = "cv_chunks"
NORMALIZED_COLLECTIONS = {
    "competence": "competences_normalisees",
    "entreprise": "entreprises_normalisees",
    "diplome": "diplomes_normalisees",
}

MERGE_THRESHOLD = 0.88
QUEUE_THRESHOLD = 0.75

VALID_NODE_TYPES = {"Candidat", "Competence", "Entreprise", "Diplome"}
DEFAULT_SUBGRAPH_LIMIT = 300
MAX_DEPTH = 4

CONSTRAINTS = [
    "CREATE CONSTRAINT candidat_id IF NOT EXISTS FOR (c:Candidat) REQUIRE c.id IS UNIQUE",
    "CREATE CONSTRAINT competence_libelle IF NOT EXISTS FOR (c:Competence) REQUIRE c.libelle IS UNIQUE",
    "CREATE CONSTRAINT entreprise_libelle IF NOT EXISTS FOR (e:Entreprise) REQUIRE e.libelle IS UNIQUE",
    "CREATE CONSTRAINT diplome_libelle IF NOT EXISTS FOR (d:Diplome) REQUIRE d.libelle IS UNIQUE",
]


# ---- Setup (called at app startup) ------------------------------------------

async def ensure_collections(qdrant: AsyncQdrantClient) -> None:
    existing = {c.name for c in (await qdrant.get_collections()).collections}
    for name in (CV_CHUNKS_COLLECTION, *NORMALIZED_COLLECTIONS.values()):
        if name not in existing:
            await qdrant.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=EMBEDDING_DIMENSION, distance=Distance.COSINE),
            )


async def ensure_constraints(neo4j_session) -> None:
    for statement in CONSTRAINTS:
        await neo4j_session.run(statement)


# ---- Indexation vectorielle (Qdrant) ----------------------------------------

def _build_summary_text(candidat: CandidatCV) -> str:
    competences = ", ".join(c.nom for c in candidat.competences)
    return (
        f"{candidat.nom or ''} {candidat.prenom or ''} — {candidat.annees_experience_cumulees or 0} ans "
        f"d'expérience. Compétences : {competences}."
    )


def _build_experience_text(exp) -> str:
    periode = f"{exp.date_debut} - {exp.date_fin or 'présent'}"
    return f"{exp.poste} chez {exp.entreprise or 'N/A'} ({periode}). {exp.description or ''}".strip()


async def index_candidat_qdrant(qdrant: AsyncQdrantClient, candidat_id: str, candidat: CandidatCV) -> None:
    points = [
        PointStruct(
            id=str(uuid.uuid4()),
            vector=get_embedding(_build_summary_text(candidat)),
            payload={"id_candidat": candidat_id, "type_chunk": "resume", "texte_brut": _build_summary_text(candidat)},
        )
    ]
    for exp in candidat.experiences:
        text = _build_experience_text(exp)
        points.append(
            PointStruct(
                id=str(uuid.uuid4()),
                vector=get_embedding(text),
                payload={"id_candidat": candidat_id, "type_chunk": "experience", "texte_brut": text},
            )
        )

    await qdrant.upsert(collection_name=CV_CHUNKS_COLLECTION, points=points)


# ---- Résolution d'entités (3 niveaux) ---------------------------------------

def normalize_label(label: str) -> str:
    text = label.strip().lower()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


async def _lookup_synonym(db: AsyncSession, normalized: str, entity_type: str) -> str | None:
    # ponytail: linear scan over the synonym table, fine at reference-data scale (dozens/hundreds
    # of rows edited from the Paramètres screen); index/cache if this table grows large.
    result = await db.execute(select(SynonymePaire).where(SynonymePaire.type_entite == entity_type))
    for pair in result.scalars().all():
        if normalize_label(pair.terme_a) == normalized or normalize_label(pair.terme_b) == normalized:
            return normalize_label(pair.terme_a)
    return None


async def _llm_disambiguate(label_a: str, label_b: str) -> bool:
    from openai import OpenAI

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    prompt = (
        f'Ces deux compétences désignent-elles la même chose : "{label_a}" et "{label_b}" ? '
        "Réponds uniquement par OUI ou NON."
    )
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=5,
    )
    answer = (response.choices[0].message.content or "").strip().upper()
    return answer.startswith("OUI")


async def _upsert_normalized_label(
    qdrant: AsyncQdrantClient, collection: str, normalized: str, embedding: list[float], canonical: str
) -> None:
    await qdrant.upsert(
        collection_name=collection,
        points=[
            PointStruct(
                id=str(uuid.uuid4()),
                vector=embedding,
                payload={"libelle_normalise": canonical, "variante": normalized},
            )
        ],
    )


async def resolve_entity(db: AsyncSession, qdrant: AsyncQdrantClient, label: str, entity_type: str) -> str:
    """3-level resolution: deterministic normalization + synonym table, then embedding
    similarity against known normalized labels, then an LLM tie-break for the ambiguous band."""
    normalized = normalize_label(label)

    synonym = await _lookup_synonym(db, normalized, entity_type)
    if synonym:
        return synonym

    collection = NORMALIZED_COLLECTIONS[entity_type]
    embedding = get_embedding(normalized)
    hits = await qdrant.search(collection_name=collection, query_vector=embedding, limit=1)

    if hits:
        best = hits[0]
        if best.score >= MERGE_THRESHOLD:
            return best.payload["libelle_normalise"]
        if best.score >= QUEUE_THRESHOLD:
            canonical = best.payload["libelle_normalise"]
            if await _llm_disambiguate(normalized, canonical):
                await _upsert_normalized_label(qdrant, collection, normalized, embedding, canonical)
                return canonical

    await _upsert_normalized_label(qdrant, collection, normalized, embedding, normalized)
    return normalized


# ---- Construction du graphe (Neo4j) -----------------------------------------

async def index_candidat_graph(
    neo4j_session, db: AsyncSession, qdrant: AsyncQdrantClient, candidat_id: str, candidat: CandidatCV
) -> None:
    await neo4j_session.run(
        "MERGE (c:Candidat {id: $id}) SET c.nom = $nom, c.prenom = $prenom, c.email = $email",
        id=candidat_id,
        nom=candidat.nom,
        prenom=candidat.prenom,
        email=candidat.email,
    )

    for comp in candidat.competences:
        libelle = await resolve_entity(db, qdrant, comp.nom, "competence")
        await neo4j_session.run(
            "MATCH (c:Candidat {id: $id}) "
            "MERGE (comp:Competence {libelle: $libelle}) "
            "MERGE (c)-[r:POSSEDE]->(comp) SET r.niveau = $niveau, r.confiance = $confiance",
            id=candidat_id,
            libelle=libelle,
            niveau=comp.niveau,
            confiance=comp.confiance,
        )

    for exp in candidat.experiences:
        if not exp.entreprise:
            continue
        libelle = await resolve_entity(db, qdrant, exp.entreprise, "entreprise")
        await neo4j_session.run(
            "MATCH (c:Candidat {id: $id}) "
            "MERGE (e:Entreprise {libelle: $libelle}) "
            "MERGE (c)-[r:A_TRAVAILLE_CHEZ]->(e) "
            "SET r.poste = $poste, r.date_debut = $date_debut, r.date_fin = $date_fin",
            id=candidat_id,
            libelle=libelle,
            poste=exp.poste,
            date_debut=exp.date_debut.isoformat(),
            date_fin=exp.date_fin.isoformat() if exp.date_fin else None,
        )

    for dip in candidat.diplomes:
        libelle = await resolve_entity(db, qdrant, dip.intitule, "diplome")
        await neo4j_session.run(
            "MATCH (c:Candidat {id: $id}) "
            "MERGE (d:Diplome {libelle: $libelle}) "
            "MERGE (c)-[r:A_OBTENU]->(d) SET r.annee_obtention = $annee",
            id=candidat_id,
            libelle=libelle,
            annee=dip.annee_obtention,
        )


# ---- Lecture du graphe (endpoints) ------------------------------------------

async def get_subgraph(
    neo4j_session,
    types: list[str] | None,
    depth: int,
    search: str | None,
    limit: int = DEFAULT_SUBGRAPH_LIMIT,
) -> dict:
    labels = [t for t in (types or []) if t in VALID_NODE_TYPES]
    depth = max(1, min(depth, MAX_DEPTH))

    if search:
        # Cypher variable-length hop counts can't be bound params; depth is clamped above so
        # interpolating it here is safe (no user-controlled string reaches the query text).
        query = (
            "MATCH (seed) WHERE toLower(coalesce(seed.libelle, seed.nom, '')) CONTAINS toLower($search) "
            f"MATCH (seed)-[*0..{depth}]-(n) "
            "WITH DISTINCT n "
            "WHERE size($labels) = 0 OR any(l IN labels(n) WHERE l IN $labels) "
            "RETURN n LIMIT $limit"
        )
    else:
        query = (
            "MATCH (n) WHERE size($labels) = 0 OR any(l IN labels(n) WHERE l IN $labels) RETURN n LIMIT $limit"
        )

    result = await neo4j_session.run(query, search=search, labels=labels, limit=limit + 1)
    records = [record async for record in result]
    truncated = len(records) > limit
    records = records[:limit]

    nodes = []
    node_ids: list[str] = []
    for record in records:
        node = record["n"]
        node_id = node.element_id
        node_ids.append(node_id)
        node_labels = list(node.labels)
        nodes.append(
            {
                "id": node_id,
                "type": node_labels[0] if node_labels else "Unknown",
                "label": node.get("libelle") or node.get("nom") or node_id,
                "properties": dict(node),
            }
        )

    links = []
    if node_ids:
        rel_result = await neo4j_session.run(
            "MATCH (a)-[r]->(b) WHERE elementId(a) IN $ids AND elementId(b) IN $ids "
            "RETURN elementId(a) AS source, elementId(b) AS target, type(r) AS type",
            ids=node_ids,
        )
        links = [
            {"source": rec["source"], "target": rec["target"], "type": rec["type"]} async for rec in rel_result
        ]

    return {"nodes": nodes, "links": links, "truncated": truncated}


async def get_node_detail(neo4j_session, node_id: str) -> dict | None:
    result = await neo4j_session.run(
        "MATCH (n) WHERE elementId(n) = $node_id RETURN n, labels(n) AS labels", node_id=node_id
    )
    record = await result.single()
    if record is None:
        return None

    node = record["n"]
    node_labels = record["labels"]
    node_type = node_labels[0] if node_labels else "Unknown"

    if node_type == "Candidat":
        rel_result = await neo4j_session.run(
            "MATCH (c:Candidat) WHERE elementId(c) = $node_id "
            "MATCH (c)-[r]->(m) "
            "RETURN type(r) AS rel_type, m",
            node_id=node_id,
        )
        relations = [{"type": rec["rel_type"], "node": dict(rec["m"])} async for rec in rel_result]
        return {"id": node_id, "type": node_type, "properties": dict(node), "relations": relations}

    rel_result = await neo4j_session.run(
        "MATCH (n) WHERE elementId(n) = $node_id MATCH (c:Candidat)-[]->(n) RETURN c", node_id=node_id
    )
    candidats_lies = [dict(rec["c"]) async for rec in rel_result]
    return {"id": node_id, "type": node_type, "properties": dict(node), "candidats_lies": candidats_lies}
