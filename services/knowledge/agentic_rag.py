import logging
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from services.knowledge.indexing import get_embedding
from services.knowledge.models import KnowledgeChunk
from services.llm.client import LLMClient

logger = logging.getLogger("agentic_rag")


# Grading node structured outputs schema
class ChunkGrade(BaseModel):
    is_relevant: bool = Field(
        ..., description="True if the chunk is relevant to the query, False otherwise"
    )
    explanation: str = Field(
        ..., description="Brief explanation of why the chunk is relevant or irrelevant"
    )


# Query reformulation schema
class QueryRewrite(BaseModel):
    rewritten_query: str = Field(
        ..., description="The reformulated search query to optimize database retrieval"
    )


# Final Agentic RAG API response schema
class AgenticRAGResponse(BaseModel):
    answer: str = Field(..., description="The final assistant response text")
    used_chunks: list[dict[str, Any]] = Field(
        ..., description="List of knowledge chunks used to generate the answer"
    )
    steps: list[str] = Field(
        ..., description="Step-by-step execution traces of the agentic RAG loop"
    )


class AgenticRAGPipeline:
    def __init__(self):
        self.llm = LLMClient()

    async def _search_hybrid(
        self, query: str, db: AsyncSession, limit: int = 3
    ) -> list[dict[str, Any]]:
        """Helper to run hybrid text + vector search query."""
        from services.knowledge.opensearch_client import (
            INDEX_NAME,
            get_opensearch_client,
        )

        client = get_opensearch_client()
        bm25_results = []
        try:
            body = {"query": {"match": {"content": query}}, "size": limit * 2}
            res = await client.search(index=INDEX_NAME, body=body)
            for hit in res["hits"]["hits"]:
                bm25_results.append(
                    {
                        "id": hit["_id"],
                        "document_name": hit["_source"]["document_name"],
                        "content": hit["_source"]["content"],
                    }
                )
        except Exception:
            # Fallback to SQL ILIKE substring search in tests/offline mode
            stmt = (
                select(KnowledgeChunk)
                .where(KnowledgeChunk.content.ilike(f"%{query}%"))
                .limit(limit * 2)
            )
            db_res = await db.execute(stmt)
            for row in db_res.scalars().all():
                bm25_results.append(
                    {
                        "id": str(row.id),
                        "document_name": row.document_name,
                        "content": row.content,
                    }
                )
        finally:
            await client.close()

        # Vector search
        query_vector = await get_embedding(query)
        distance = KnowledgeChunk.embedding.cosine_distance(query_vector)
        v_query = (
            select(
                KnowledgeChunk.id,
                KnowledgeChunk.document_name,
                KnowledgeChunk.content,
                distance.label("distance"),
            )
            .order_by(distance)
            .limit(limit * 2)
        )

        v_res = await db.execute(v_query)
        vector_results = [
            {
                "id": str(row.id),
                "document_name": row.document_name,
                "content": row.content,
                "distance": float(row.distance),
            }
            for row in v_res.all()
        ]

        # Reciprocal Rank Fusion (RRF)
        rrf_scores = {}
        doc_details = {}
        for rank, doc in enumerate(bm25_results, start=1):
            doc_id = doc["id"]
            doc_details[doc_id] = {
                "document_name": doc["document_name"],
                "content": doc["content"],
            }
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + (1.0 / (60.0 + rank))

        for rank, doc in enumerate(vector_results, start=1):
            doc_id = doc["id"]
            doc_details[doc_id] = {
                "document_name": doc["document_name"],
                "content": doc["content"],
            }
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + (1.0 / (60.0 + rank))

        sorted_docs = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
        return [
            {
                "id": doc_id,
                "document_name": doc_details[doc_id]["document_name"],
                "content": doc_details[doc_id]["content"],
            }
            for doc_id, _ in sorted_docs[:limit]
        ]

    async def _grade_chunk(self, query: str, chunk_content: str) -> ChunkGrade:
        """LLM node to evaluate relevance of a retrieved chunk."""
        prompt = (
            f"User Query: {query}\n\n"
            f"Knowledge Chunk:\n{chunk_content}\n\n"
            f"Grade whether this chunk contains relevant information to help answer the user query."
        )
        messages = [
            {
                "role": "system",
                "content": "You are a factual retrieval evaluator. Evaluate relevance objectively.",
            },
            {"role": "user", "content": prompt},
        ]

        response = await self.llm.generate(messages=messages, response_model=ChunkGrade)
        return response.content

    async def _rewrite_query(self, query: str) -> str:
        """LLM node to rewrite the user query for better vector/text retrieval."""
        prompt = (
            f"Initial query: '{query}' yielded zero relevant results.\n"
            f"Reformulate this search query to optimize keyword and semantic search. "
            f"Keep it concise."
        )
        messages = [
            {
                "role": "system",
                "content": "You are a search expert. Rewrite the query to expand coverage.",
            },
            {"role": "user", "content": prompt},
        ]

        response = await self.llm.generate(
            messages=messages, response_model=QueryRewrite
        )
        return response.content.rewritten_query

    async def execute(self, query: str, db: AsyncSession) -> AgenticRAGResponse:
        steps = []

        # Step 1: Initial Hybrid Search
        steps.append(f"Step 1: Running initial search for query: '{query}'")
        chunks = await self._search_hybrid(query, db)
        steps.append(f"Retrieved {len(chunks)} candidate chunks from search.")

        # Step 2: Grade retrieved chunks
        relevant_chunks = []
        for idx, chunk in enumerate(chunks, start=1):
            grade = await self._grade_chunk(query, chunk["content"])
            steps.append(
                f"Grading chunk {idx} ({chunk['document_name']}): is_relevant={grade.is_relevant} (Explanation: {grade.explanation})"
            )
            if grade.is_relevant:
                relevant_chunks.append(chunk)

        # Step 3: If relevant context found, answer immediately
        if relevant_chunks:
            steps.append("Relevant context found. Proceeding to generate final answer.")
            answer = await self._generate_answer(query, relevant_chunks)
            return AgenticRAGResponse(
                answer=answer, used_chunks=relevant_chunks, steps=steps
            )

        # Step 4: No relevant chunks - Trigger Query Rewrite
        steps.append("No relevant context found. Triggering Query Rewrite Node.")
        rewritten_query = await self._rewrite_query(query)
        steps.append(f"Step 4: Rewrote query to: '{rewritten_query}'")

        # Step 5: Second Search with rewritten query
        steps.append("Running second search using rewritten query.")
        new_chunks = await self._search_hybrid(rewritten_query, db)
        steps.append(
            f"Retrieved {len(new_chunks)} candidate chunks from second search."
        )

        # Step 6: Grade new chunks
        for idx, chunk in enumerate(new_chunks, start=1):
            grade = await self._grade_chunk(rewritten_query, chunk["content"])
            steps.append(
                f"Grading second search chunk {idx} ({chunk['document_name']}): is_relevant={grade.is_relevant} (Explanation: {grade.explanation})"
            )
            if grade.is_relevant:
                relevant_chunks.append(chunk)

        # Step 7: Answer if new chunks are relevant, else route to Fallback Handoff
        if relevant_chunks:
            steps.append(
                "Relevant context found after query rewrite. Proceeding to answer."
            )
            answer = await self._generate_answer(query, relevant_chunks)
            return AgenticRAGResponse(
                answer=answer, used_chunks=relevant_chunks, steps=steps
            )

        steps.append(
            "No relevant context found after rewrite. Routing to Fallback Customer Handoff."
        )
        fallback_answer = (
            f"I searched our knowledge database for '{query}' but couldn't locate "
            f"an exact answer. Let me know if you would like me to connect you to a human support agent."
        )
        return AgenticRAGResponse(answer=fallback_answer, used_chunks=[], steps=steps)

    async def _generate_answer(self, query: str, context_chunks: list[dict]) -> str:
        """Prompts LLM to write a final answer using only the provided context chunks."""
        context_str = "\n\n".join(
            f"Source: {c['document_name']}\nContent: {c['content']}"
            for c in context_chunks
        )
        prompt = (
            f"User Query: {query}\n\n"
            f"Context Documents:\n{context_str}\n\n"
            f"Please answer the user query accurately based ONLY on the provided context documents."
        )
        messages = [
            {
                "role": "system",
                "content": "You are a customer support agent. Answer questions using only the context provided.",
            },
            {"role": "user", "content": prompt},
        ]

        response = await self.llm.generate(messages=messages)
        return response.content
