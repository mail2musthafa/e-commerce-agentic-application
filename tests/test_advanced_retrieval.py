import asyncio

from fastapi.testclient import TestClient
from sqlalchemy import delete

from apps.api.main import app
from services.database import async_session
from services.knowledge.models import KnowledgeChunk

client = TestClient(app)


def test_hybrid_search_retrieval_flow():
    # 0. Clean up database to ensure isolation
    async def cleanup():
        async with async_session() as db:
            await db.execute(delete(KnowledgeChunk))
            await db.commit()

    asyncio.run(cleanup())

    # 1. Index a document
    index_payload = {
        "document_name": "faq_cancellation.md",
        "content": (
            "Cancellation Policy: Customers can cancel their orders within 24 hours of purchase "
            "for a full refund. Cancellations after 24 hours are subject to a 10% restock fee."
        ),
        "chunk_size": 150,
        "chunk_overlap": 20,
    }
    response = client.post("/knowledge/index", json=index_payload)
    assert response.status_code == 201

    # 2. Run a hybrid search query (RRF BM25 + Vector)
    search_payload = {"query": "cancellation policy within 24 hours", "top_k": 2}
    search_response = client.post("/knowledge/hybrid_search", json=search_payload)
    assert search_response.status_code == 200

    results = search_response.json()
    assert len(results) > 0

    # 3. Assert the best matching chunk is correctly retrieved
    top_match = results[0]
    assert top_match["document_name"] == "faq_cancellation.md"
    assert "cancel" in top_match["content"].lower()
    assert "distance" in top_match  # Score is returned mapped to distance
