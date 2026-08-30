from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from services.database import get_db
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
        # 2. Generate embeddings and create records
        for chunk in chunks:
            vector = await get_embedding(chunk)
            knowledge_chunk = KnowledgeChunk(
                document_name=payload.document_name, content=chunk, embedding=vector
            )
            db.add(knowledge_chunk)

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
