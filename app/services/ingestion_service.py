import json
import logging
from datetime import date
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.cv import CV, CVStatus
from app.models.notification import NotificationType
from app.models.user import UserRole
from app.schemas.candidat import CandidatCV, ExperiencePro
from app.services.notification_service import notifier_roles

logger = logging.getLogger("ingestion")

REQUIRED_FIELDS = ("nom", "prenom", "email", "experiences")
CONFIDENCE_THRESHOLD = 0.6
GLINER_LABELS = ["PERSON", "SKILL", "DEGREE", "ROLE", "COMPANY", "EMAIL", "PHONE", "DATE_RANGE", "LOCATION"]
MIN_TEXT_LENGTH = 200

# GPT-4o-mini pricing (USD per token), used only for cost logging.
_PRICE_PER_INPUT_TOKEN = 0.15 / 1_000_000
_PRICE_PER_OUTPUT_TOKEN = 0.60 / 1_000_000

_gliner_model = None


def get_gliner_model():
    """Lazy singleton — loaded once per Celery worker process (see worker_process_init in ingestion_tasks.py),
    not on every task invocation."""
    global _gliner_model
    if _gliner_model is None:
        from gliner import GLiNER

        _gliner_model = GLiNER.from_pretrained("urchade/gliner_multi-v2.1")
    return _gliner_model


# ---- 1. Extraction du texte brut -------------------------------------------

def extract_text(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf_text(file_path)
    if suffix == ".docx":
        return _extract_docx_text(file_path)
    if suffix == ".txt":
        return file_path.read_text(encoding="utf-8", errors="ignore")
    raise ValueError(f"Extension non supportée: {suffix}")


def _extract_pdf_text(file_path: Path) -> str:
    try:
        import pdfplumber

        with pdfplumber.open(file_path) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        if text.strip():
            return text
    except Exception:
        logger.warning("pdfplumber failed for %s, falling back to PyMuPDF", file_path, exc_info=True)

    import fitz  # PyMuPDF

    doc = fitz.open(file_path)
    return "\n".join(page.get_text() for page in doc)


def _extract_docx_text(file_path: Path) -> str:
    import docx

    doc = docx.Document(file_path)
    return "\n".join(p.text for p in doc.paragraphs)


def ocr_fallback(file_path: Path) -> str:
    from pdf2image import convert_from_path
    import pytesseract

    images = convert_from_path(file_path)
    return "\n".join(pytesseract.image_to_string(img, lang="fra+eng") for img in images)


# ---- 3. Détection de langue -------------------------------------------------

def detect_language(text: str) -> str | None:
    from langdetect import LangDetectException, detect

    try:
        return detect(text)
    except LangDetectException:
        return None


# ---- 4. NER (GliNER) --------------------------------------------------------

def extract_entities(text: str) -> list[dict]:
    model = get_gliner_model()
    return model.predict_entities(text, GLINER_LABELS)


# ---- 5. Structuration LLM (GPT-4o-mini, function calling) ------------------

def structure_with_llm(text: str, entities: list[dict]) -> tuple[CandidatCV, dict]:
    """Structures raw text + NER hints into a CandidatCV via GPT-4o-mini function calling.
    Retries once (2 attempts total) if the response fails Pydantic validation."""
    from openai import OpenAI

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    schema = CandidatCV.model_json_schema()
    entities_hint = json.dumps(entities, ensure_ascii=False)

    messages = [
        {
            "role": "system",
            "content": (
                "Tu extrais les informations structurées d'un CV. Utilise les entités déjà "
                "détectées comme indices mais vérifie-les dans le texte complet. Attribue un "
                "score de confiance (0 à 1) à chaque champ obligatoire extrait dans `source_confiance`."
            ),
        },
        {"role": "user", "content": f"Entités détectées (NER) :\n{entities_hint}\n\nTexte du CV :\n{text}"},
    ]

    last_error: Exception | None = None
    for _ in range(2):
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "structurer_cv",
                        "description": "Structure les données d'un CV selon le schéma CandidatCV",
                        "parameters": schema,
                    },
                }
            ],
            tool_choice={"type": "function", "function": {"name": "structurer_cv"}},
        )
        usage = response.usage
        tool_call = response.choices[0].message.tool_calls[0]
        try:
            candidat = CandidatCV.model_validate_json(tool_call.function.arguments)
            return candidat, {
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
            }
        except Exception as exc:  # pydantic ValidationError
            last_error = exc
            messages.append(
                {
                    "role": "user",
                    "content": f"La réponse précédente ne respecte pas le schéma ({exc}). Corrige et renvoie un JSON valide.",
                }
            )

    raise ValueError(f"Échec de structuration LLM après 2 tentatives: {last_error}")


def log_llm_cost(cv_id: UUID, usage: dict) -> None:
    cost_usd = (
        usage["prompt_tokens"] * _PRICE_PER_INPUT_TOKEN + usage["completion_tokens"] * _PRICE_PER_OUTPUT_TOKEN
    )
    logger.info(
        json.dumps(
            {
                "event": "llm_cost",
                "cv_id": str(cv_id),
                "model": "gpt-4o-mini",
                "prompt_tokens": usage["prompt_tokens"],
                "completion_tokens": usage["completion_tokens"],
                "cost_usd": round(cost_usd, 6),
            }
        )
    )


# ---- 6. Années d'expérience cumulées (fusion d'intervalles) ----------------

def compute_years_experience(experiences: list[ExperiencePro]) -> float:
    intervals = sorted(
        ((e.date_debut, e.date_fin or date.today()) for e in experiences if e.date_debut),
        key=lambda interval: interval[0],
    )

    merged: list[list[date]] = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    total_days = sum((end - start).days for start, end in merged)
    return round(total_days / 365.25, 1)


# ---- 7. Statut qualité -------------------------------------------------------

def compute_quality_status(candidat: CandidatCV) -> tuple[str, list[str]]:
    champs_a_verifier = [
        field for field in REQUIRED_FIELDS if candidat.source_confiance.get(field, 0.0) < CONFIDENCE_THRESHOLD
    ]
    statut = "a_valider" if champs_a_verifier else "ok"
    return statut, champs_a_verifier


# ---- Orchestration (appelée par la tâche Celery) ----------------------------

async def _notifier_echec_parsing(db: AsyncSession, cv: CV) -> None:
    await notifier_roles(
        db,
        (UserRole.ADMIN, UserRole.RH_INTERNE),
        NotificationType.CV_ECHEC,
        f"Échec du parsing pour le CV « {cv.nom_fichier} ».",
    )


async def run_pipeline(db: AsyncSession, cv_id: UUID) -> None:
    cv = await db.get(CV, cv_id)
    if cv is None:
        return

    file_path = Path(cv.storage_path)
    try:
        text = extract_text(file_path)
    except Exception:
        logger.exception("Text extraction failed for CV %s", cv_id)
        cv.statut = CVStatus.ECHEC_PARSING
        await db.commit()
        await _notifier_echec_parsing(db, cv)
        return

    if len(text.strip()) < MIN_TEXT_LENGTH and file_path.suffix.lower() == ".pdf":
        try:
            text = ocr_fallback(file_path)
        except Exception:
            logger.warning("OCR fallback failed for CV %s", cv_id, exc_info=True)

    if len(text.strip()) < MIN_TEXT_LENGTH:
        cv.statut = CVStatus.ECHEC_PARSING
        await db.commit()
        await _notifier_echec_parsing(db, cv)
        return

    langue = detect_language(text)
    entities = extract_entities(text)
    candidat, usage = structure_with_llm(text, entities)
    log_llm_cost(cv_id, usage)

    candidat.langue_detectee = langue
    candidat.annees_experience_cumulees = compute_years_experience(candidat.experiences)
    statut, champs_a_verifier = compute_quality_status(candidat)
    candidat.statut_qualite = statut
    candidat.champs_a_verifier = champs_a_verifier

    cv.statut = CVStatus(statut)
    cv.score_confiance_global = (
        round(sum(candidat.source_confiance.values()) / len(candidat.source_confiance), 2)
        if candidat.source_confiance
        else 0.0
    )
    cv.donnees_json = candidat.model_dump(mode="json")
    cv.champs_a_verifier = champs_a_verifier
    await db.commit()

    if statut == "ok":
        from app.tasks.ingestion_tasks import trigger_indexing

        trigger_indexing.delay(str(cv_id))
