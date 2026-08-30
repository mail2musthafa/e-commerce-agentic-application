import uuid

from pydantic import BaseModel, ConfigDict, Field


class DocumentIndexRequest(BaseModel):
    document_name: str = Field(
        ..., description="The name of the source document (e.g. 'faq.md')"
    )
    content: str = Field(
        ..., description="The full textual content of the document to chunk and index"
    )
    chunk_size: int = Field(500, description="The maximum size of each text segment")
    chunk_overlap: int = Field(
        50, description="The character overlap between consecutive chunks"
    )


class IndexResultResponse(BaseModel):
    status: str
    chunks_created: int


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(..., description="The search query text")
    top_k: int = Field(
        3, ge=1, le=20, description="Number of top matching chunks to retrieve"
    )


class KnowledgeChunkRead(BaseModel):
    id: uuid.UUID
    document_name: str
    content: str
    distance: float = Field(
        ..., description="Similarity distance score (lower is more similar)"
    )

    model_config = ConfigDict(from_attributes=True)
