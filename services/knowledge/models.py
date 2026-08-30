import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, String, Text
from sqlalchemy.dialects.postgresql import UUID

from services.database import Base


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_name = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    # 1536 dimensions corresponding to OpenAI text-embedding-3-small
    embedding = Column(Vector(1536), nullable=False)
