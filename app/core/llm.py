import time
from typing import TypeVar

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel

from app.core.config import settings

# Tried in order; the first model that answers wins. Gemini periodically retires
# or renames models (an old one can start 404-ing as "no longer available to new
# users"), so a fallback chain avoids a hard outage when one entry stops working -
# update this list if a model in it gets deprecated.
GEMINI_MODELS = [
    "gemini-flash-latest",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
]

T = TypeVar("T", bound=BaseModel)

_client: genai.Client | None = None


def get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


def _generate(contents: str, config: types.GenerateContentConfig):
    """Runs generate_content across GEMINI_MODELS, retrying once per model on a
    transient server error before falling through to the next model."""
    client = get_client()
    last_error: Exception | None = None
    for model in GEMINI_MODELS:
        for attempt in range(2):
            try:
                return client.models.generate_content(model=model, contents=contents, config=config), model
            except Exception as exc:
                last_error = exc
                if attempt == 0 and isinstance(exc, genai_errors.ServerError):
                    time.sleep(1.5)
                    continue
                break
    raise last_error


def generate_structured(
    contents: str, response_schema: type[T], system_instruction: str | None = None
) -> tuple[T, dict]:
    """Calls Gemini with structured JSON output validated against response_schema.
    Returns the parsed model plus token usage (including which model answered)."""
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        response_schema=response_schema,
    )
    response, model = _generate(contents, config)
    usage = response.usage_metadata
    return response.parsed, {
        "model": model,
        "prompt_tokens": usage.prompt_token_count or 0,
        "completion_tokens": usage.candidates_token_count or 0,
    }


def generate_text(contents: str, system_instruction: str | None = None) -> str:
    """Plain-text Gemini call (no structured schema), same model fallback chain."""
    config = types.GenerateContentConfig(system_instruction=system_instruction)
    response, _model = _generate(contents, config)
    return (response.text or "").strip()
