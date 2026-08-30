from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from services.database import get_db
from services.knowledge.agentic_rag import AgenticRAGPipeline, AgenticRAGResponse
from services.knowledge.indexing import get_embedding, split_text
from services.knowledge.models import KnowledgeChunk
from services.knowledge.schemas import (
    DocumentIndexRequest,
    IndexResultResponse,
    KnowledgeChunkRead,
    KnowledgeSearchRequest,
)

router = APIRouter(prefix="/knowledge", tags=["Knowledge Base"])


@router.post(
    "/index", response_model=IndexResultResponse, status_code=status.HTTP_201_CREATED
)
async def index_document(
    payload: DocumentIndexRequest, db: AsyncSession = Depends(get_db)
):
    # 1. Chunk the document text
    chunks = split_text(
        payload.content,
        chunk_size=payload.chunk_size,
        chunk_overlap=payload.chunk_overlap,
    )

    if not chunks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Document content is empty"
        )

    try:
        # 2. Generate embeddings and create records in PostgreSQL + OpenSearch
        from services.knowledge.indexing import index_chunk_in_opensearch

        for chunk in chunks:
            vector = await get_embedding(chunk)
            knowledge_chunk = KnowledgeChunk(
                document_name=payload.document_name, content=chunk, embedding=vector
            )
            db.add(knowledge_chunk)
            await db.flush()  # To populate knowledge_chunk.id

            # Async push to OpenSearch HNSW KNN index
            await index_chunk_in_opensearch(
                chunk_id=str(knowledge_chunk.id),
                document_name=payload.document_name,
                content=chunk,
                embedding=vector,
            )

        await db.commit()
        return IndexResultResponse(status="success", chunks_created=len(chunks))

    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to index document: {str(e)}",
        ) from e


@router.post("/search", response_model=list[KnowledgeChunkRead])
async def search_knowledge(
    payload: KnowledgeSearchRequest, db: AsyncSession = Depends(get_db)
):
    try:
        # 1. Embed query
        query_vector = await get_embedding(payload.query)

        # 2. Perform cosine distance search using pgvector
        distance = KnowledgeChunk.embedding.cosine_distance(query_vector)
        query = (
            select(
                KnowledgeChunk.id,
                KnowledgeChunk.document_name,
                KnowledgeChunk.content,
                distance.label("distance"),
            )
            .order_by(distance)
            .limit(payload.top_k)
        )

        res = await db.execute(query)
        rows = res.all()

        # 3. Map database rows to output Pydantic read models
        return [
            KnowledgeChunkRead(
                id=row.id,
                document_name=row.document_name,
                content=row.content,
                distance=float(row.distance),
            )
            for row in rows
        ]

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Vector search failed: {str(e)}",
        ) from e


@router.post("/hybrid_search", response_model=list[KnowledgeChunkRead])
async def search_hybrid(
    payload: KnowledgeSearchRequest, db: AsyncSession = Depends(get_db)
):
    try:
        # 1. Fetch BM25 Results from OpenSearch (with SQL fallback if offline/in test environment)
        from services.knowledge.opensearch_client import (
            INDEX_NAME,
            get_opensearch_client,
        )

        client = get_opensearch_client()
        bm25_results = []
        try:
            body = {
                "query": {"match": {"content": payload.query}},
                "size": payload.top_k * 2,
            }
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
            # Fallback to a basic ILIKE substring query in SQL
            stmt = (
                select(KnowledgeChunk)
                .where(KnowledgeChunk.content.ilike(f"%{payload.query}%"))
                .limit(payload.top_k * 2)
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

        # 2. Fetch Vector Similarity Results from pgvector
        query_vector = await get_embedding(payload.query)
        distance = KnowledgeChunk.embedding.cosine_distance(query_vector)
        v_query = (
            select(
                KnowledgeChunk.id,
                KnowledgeChunk.document_name,
                KnowledgeChunk.content,
                distance.label("distance"),
            )
            .order_by(distance)
            .limit(payload.top_k * 2)
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

        # 3. Reciprocal Rank Fusion (RRF) Ranking Merging (using constant k=60)
        rrf_scores = {}
        doc_details = {}

        # BM25 ranks
        for rank, doc in enumerate(bm25_results, start=1):
            doc_id = doc["id"]
            doc_details[doc_id] = {
                "document_name": doc["document_name"],
                "content": doc["content"],
            }
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + (1.0 / (60.0 + rank))

        # KNN ranks
        for rank, doc in enumerate(vector_results, start=1):
            doc_id = doc["id"]
            doc_details[doc_id] = {
                "document_name": doc["document_name"],
                "content": doc["content"],
            }
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + (1.0 / (60.0 + rank))

        # Sort and get top_k
        sorted_docs = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
        top_docs = sorted_docs[: payload.top_k]

        return [
            KnowledgeChunkRead(
                id=doc_id,
                document_name=doc_details[doc_id]["document_name"],
                content=doc_details[doc_id]["content"],
                distance=1.0 - score,
            )
            for doc_id, score in top_docs
        ]

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Hybrid search failed: {str(e)}",
        ) from e


@router.post("/agentic_search", response_model=AgenticRAGResponse)
async def search_agentic(
    payload: KnowledgeSearchRequest, db: AsyncSession = Depends(get_db)
):
    pipeline = AgenticRAGPipeline()
    try:
        response = await pipeline.execute(payload.query, db)
        return response
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Agentic RAG pipeline failed: {str(e)}",
        ) from e
