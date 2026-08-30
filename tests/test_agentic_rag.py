import asyncio

from fastapi.testclient import TestClient
from sqlalchemy import delete

from apps.api.main import app
from services.database import async_session
from services.knowledge.models import KnowledgeChunk

client = TestClient(app)


def test_agentic_rag_happy_path():
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

    # 1. Index return policy document
    index_payload = {
        "document_name": "return_policy.md",
        "content": (
            "Return Policy: Items must be returned within 30 days of receipt. "
            "Returns must be in original condition with tags intact."
        ),
        "chunk_size": 150,
        "chunk_overlap": 20,
    }
    response = client.post("/knowledge/index", json=index_payload)
    assert response.status_code == 201

    # 2. Run agentic RAG query (relevant to index)
    search_payload = {"query": "What is the return period?", "top_k": 2}
    search_response = client.post("/knowledge/agentic_search", json=search_payload)
    assert search_response.status_code == 200

    data = search_response.json()
    assert "answer" in data
    assert len(data["used_chunks"]) > 0
    assert data["used_chunks"][0]["document_name"] == "return_policy.md"

    # Verify traces show grading node execution
    assert any("is_relevant=True" in step for step in data["steps"])


def test_agentic_rag_fallback_path():
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

    # 1. Index return policy document (irrelevant to query)
    index_payload = {
        "document_name": "return_policy.md",
        "content": ("Return Policy: Items must be returned within 30 days of receipt."),
        "chunk_size": 150,
        "chunk_overlap": 20,
    }
    client.post("/knowledge/index", json=index_payload)

    # 2. Run query containing "unknown" or "unrelated" keyword to trigger fallback branches
    search_payload = {"query": "What is the unknown unrelated policy?", "top_k": 2}
    search_response = client.post("/knowledge/agentic_search", json=search_payload)
    assert search_response.status_code == 200

    data = search_response.json()
    # Confirm fallback handoff message is returned
    assert "connect you to a human support agent" in data["answer"]
    assert len(data["used_chunks"]) == 0

    # Verify traces capture RRF search, grading node rejection, query rewriting, and fallback handoffs
    assert any("Triggering Query Rewrite Node" in step for step in data["steps"])
    assert any("Routing to Fallback Customer Handoff" in step for step in data["steps"])
