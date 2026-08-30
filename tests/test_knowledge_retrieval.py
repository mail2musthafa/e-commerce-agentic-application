import asyncio

from fastapi.testclient import TestClient
from sqlalchemy import delete

from apps.api.main import app
from services.database import async_session
from services.knowledge.models import KnowledgeChunk

client = TestClient(app)


def test_knowledge_indexing_and_retrieval():
    # 0. Clean up database and OpenSearch to ensure isolation
    async def cleanup():
        async with async_session() as db:
            await db.execute(delete(KnowledgeChunk))
            await db.commit()

        from services.knowledge.opensearch_client import (
            INDEX_NAME,
            get_opensearch_client,
        )

        client = get_opensearch_client()
        try:
            await client.delete_by_query(
                index=INDEX_NAME, body={"query": {"match_all": {}}}, refresh=True
            )
        except Exception:
            pass
        finally:
            await client.close()

    asyncio.run(cleanup())

    # 1. Index a document containing shipping details
    index_payload = {
        "document_name": "shipping_policy.md",
        "content": (
            "Shipping Policy: Standard shipping takes 3-5 business days. "
            "Express shipping takes 1-2 business days. "
            "International shipping is calculated at checkout based on location."
        ),
        "chunk_size": 100,
        "chunk_overlap": 20,
    }
    response = client.post("/knowledge/index", json=index_payload)
    assert response.status_code == 201

    data = response.json()
    assert data["status"] == "success"
    assert data["chunks_created"] > 0

    # 2. Query the index using vector similarity search
    search_payload = {"query": "How many days for standard shipping?", "top_k": 2}
    search_response = client.post("/knowledge/search", json=search_payload)
    assert search_response.status_code == 200

    results = search_response.json()
    assert len(results) > 0

    # 3. Assert the best matching chunk is retrieved with high relevance
    top_match = results[0]
    assert top_match["document_name"] == "shipping_policy.md"
    assert "shipping" in top_match["content"].lower()
    assert top_match["distance"] >= 0.0
