import datetime
import uuid

from pydantic import BaseModel, ConfigDict, Field


class ChatMessageSchema(BaseModel):
    role: str = Field(
        ..., description="The role of the message author (system, user, assistant)"
    )
    content: str = Field(..., description="The content of the message")


class ChatMessageRead(BaseModel):
    id: uuid.UUID
    session_id: str
    role: str
    content: str
    created_at: datetime.datetime

    model_config = ConfigDict(from_attributes=True)


class SessionHistoryResponse(BaseModel):
    session_id: str
    messages: list[ChatMessageSchema]
