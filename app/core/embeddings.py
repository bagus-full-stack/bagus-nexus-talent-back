from google.genai import types

from app.core.llm import get_client

EMBEDDING_MODEL = "gemini-embedding-001"
# Gemini's embedding model natively outputs 3072 dims but supports Matryoshka
# truncation via output_dimensionality - kept at 1536 to match the existing
# Qdrant collections without a reindex.
EMBEDDING_DIMENSION = 1536


def get_embedding(text: str) -> list[float]:
    response = get_client().models.embed_content(
        model=EMBEDDING_MODEL,
        contents=text,
        config=types.EmbedContentConfig(output_dimensionality=EMBEDDING_DIMENSION),
    )
    return response.embeddings[0].values
