import hashlib
import json
import uuid
from datetime import datetime, timezone

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cv import CV
from app.models.gdpr_request import GDPRRequest, GDPRRequestStatus, GDPRRequestType
from app.models.notification import NotificationType
from app.services.graph_service import CV_CHUNKS_COLLECTION
from app.services.notification_service import creer_notification


def _audit_hash(candidat_id: str, timestamp: str, nombre_elements_supprimes: int) -> str:
    payload = json.dumps(
        {"candidat_id": candidat_id, "timestamp": timestamp, "nombre_elements_supprimes": nombre_elements_supprimes},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def supprimer_candidat(neo4j_session, qdrant: AsyncQdrantClient, db: AsyncSession, candidat_id: str) -> dict:
    """Droit à l'effacement : supprime uniquement le nœud Candidat (jamais les entités
    Competence/Entreprise/Diplome partagées), les vecteurs Qdrant du candidat, et la
    ligne CV en Postgres. Retourne une preuve d'audit (hash SHA-256)."""

    # 1. Graphe : compte les relations avant DETACH DELETE, qui ne touche que le nœud Candidat.
    count_result = await neo4j_session.run(
        "MATCH (c:Candidat {id: $id})-[r]-() RETURN count(r) AS total", id=candidat_id
    )
    record = await count_result.single()
    relations_supprimees = record["total"] if record else 0

    await neo4j_session.run("MATCH (c:Candidat {id: $id}) DETACH DELETE c", id=candidat_id)

    # 2. Vecteurs Qdrant filtrés par id_candidat.
    id_filter = Filter(must=[FieldCondition(key="id_candidat", match=MatchValue(value=candidat_id))])
    count_response = await qdrant.count(collection_name=CV_CHUNKS_COLLECTION, count_filter=id_filter)
    vecteurs_supprimes = count_response.count
    await qdrant.delete(collection_name=CV_CHUNKS_COLLECTION, points_selector=FilterSelector(filter=id_filter))

    # 3. Postgres : entrée CV et métadonnées.
    cv = await db.get(CV, uuid.UUID(candidat_id))
    if cv is not None:
        await db.delete(cv)
        await db.commit()

    # 4. Preuve d'audit.
    timestamp = datetime.now(timezone.utc).isoformat()
    hash_audit = _audit_hash(candidat_id, timestamp, relations_supprimees + vecteurs_supprimes)

    return {
        "relations_supprimees": relations_supprimees,
        "vecteurs_supprimes": vecteurs_supprimes,
        "hash_audit": hash_audit,
    }


async def anonymiser_candidat(db: AsyncSession, candidat_id: str) -> dict:
    """Anonymise les champs identifiants en Postgres uniquement — le graphe et les vecteurs
    ne sont pas touchés, les données non-identifiantes restent pour les statistiques agrégées."""
    cv = await db.get(CV, uuid.UUID(candidat_id))
    if cv is None or cv.donnees_json is None:
        return {"champs_anonymises": []}

    data = dict(cv.donnees_json)
    for field in ("nom", "email", "telephone"):
        data[field] = None
    cv.donnees_json = data
    await db.commit()

    return {"champs_anonymises": ["nom", "email", "telephone"]}


async def executer_demande(
    db: AsyncSession, qdrant: AsyncQdrantClient, neo4j_session, demande: GDPRRequest
) -> GDPRRequest:
    """Exécute une demande RGPD déjà validée (mot de passe et statut vérifiés par l'appelant) et
    notifie l'admin demandeur, que l'exécution réussisse ou échoue."""
    demande.statut = GDPRRequestStatus.EN_COURS
    await db.commit()

    try:
        if demande.type == GDPRRequestType.SUPPRESSION:
            resultat = await supprimer_candidat(neo4j_session, qdrant, db, str(demande.candidat_id))
        else:
            resultat = await anonymiser_candidat(db, str(demande.candidat_id))
        demande.statut = GDPRRequestStatus.TERMINEE
        demande.resultat_json = resultat
        texte = f"Demande RGPD ({demande.type.value}) terminée avec succès pour le candidat {demande.candidat_id}."
    except Exception as exc:
        demande.statut = GDPRRequestStatus.ECHEC
        demande.resultat_json = {"erreur": str(exc)}
        texte = f"Échec de la demande RGPD ({demande.type.value}) pour le candidat {demande.candidat_id}."

    demande.date_execution = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(demande)

    await creer_notification(db, demande.demande_par, NotificationType.GDPR_TERMINEE, texte)
    return demande


async def nettoyer_entites_orphelines(neo4j_session) -> int:
    """Supprime les nœuds Competence/Entreprise/Diplome sans relation entrante (job Celery beat
    hebdomadaire) et renvoie le nombre de nœuds supprimés."""
    result = await neo4j_session.run(
        "MATCH (n) WHERE (n:Competence OR n:Entreprise OR n:Diplome) AND NOT ()-->(n) "
        "WITH collect(n) AS orphelins "
        "UNWIND orphelins AS n "
        "DETACH DELETE n "
        "RETURN size(orphelins) AS removed"
    )
    record = await result.single()
    return record["removed"] if record else 0
