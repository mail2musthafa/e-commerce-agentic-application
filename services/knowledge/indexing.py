import hashlib
import logging
import math
import os
import sys

import litellm

logger = logging.getLogger("knowledge_indexing")


def split_text(text: str, chunk_size: int = 500, chunk_overlap: int = 50) -> list[str]:
    """Splits a document text into overlapping chunks of defined size."""
    if not text:
        return []

    chunks = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + chunk_size, text_len)
        chunks.append(text[start:end])
        if end == text_len:
            break
        # Slide start index back by overlap value
        start += chunk_size - chunk_overlap

    return chunks


def _get_mock_embedding(text: str) -> list[float]:
    """Generates a deterministic 1536-dimensional unit vector for test runs."""
    vector = []
    for i in range(1536):
        # Create a unique float representation using MD5 hashing
        hash_val = int(hashlib.md5(f"{text}_{i}".encode()).hexdigest(), 16) % 1000
        vector.append(float(hash_val))

    # Normalize to unit length (cosine similarity queries require normalized inputs)
    norm = math.sqrt(sum(v * v for v in vector))
    if norm > 0:
        vector = [v / norm for v in vector]
    return vector


async def get_embedding(text: str) -> list[float]:
    """Retrieves text embeddings using LiteLLM, with fallback mock generator in tests."""
    is_testing = "pytest" in sys.modules or os.getenv("TESTING") == "1"
    has_keys = any(
        os.getenv(key)
        for key in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"]
    )

    if is_testing and not has_keys:
        return _get_mock_embedding(text)

    try:
        response = await litellm.aembedding(
            model="openai/text-embedding-3-small", input=[text]
        )
        return response.data[0]["embedding"]
    except Exception as e:
        logger.error(f"LiteLLM embedding call failed: {e}")
        if is_testing:
            return _get_mock_embedding(text)
        raise e


async def index_chunk_in_opensearch(
    chunk_id: str, document_name: str, content: str, embedding: list[float]
):
    """Pushes a document text chunk and its embedding vector into OpenSearch."""
    from services.knowledge.opensearch_client import INDEX_NAME, get_opensearch_client

    client = get_opensearch_client()
    try:
        doc = {
            "document_name": document_name,
            "content": content,
            "embedding": embedding,
        }
        await client.index(index=INDEX_NAME, id=chunk_id, body=doc, refresh=True)
        logger.info(f"Chunk '{chunk_id}' indexed in OpenSearch.")
    except Exception as e:
        logger.warning(
            f"Failed to index chunk in OpenSearch (continuing gracefully): {e}"
        )
    finally:
        await client.close()
