import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from services.database import get_db, get_redis
from services.memory.schemas import ChatMessageSchema, SessionHistoryResponse
from services.memory.service import add_message, clear_session, get_messages

router = APIRouter(prefix="/memory", tags=["Session Memory"])


@router.post(
    "/session/{session_id}/message",
    response_model=ChatMessageSchema,
    status_code=status.HTTP_201_CREATED,
)
async def post_message(
    session_id: str,
    payload: ChatMessageSchema,
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
):
    try:
        await add_message(
            session_id=session_id,
            role=payload.role,
            content=payload.content,
            db=db,
            redis_client=redis_client,
        )
        return payload
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to post message to session: {str(e)}",
        ) from e


@router.get("/session/{session_id}", response_model=SessionHistoryResponse)
async def get_history(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
):
    try:
        messages = await get_messages(
            session_id=session_id, db=db, redis_client=redis_client
        )
        return SessionHistoryResponse(
            session_id=session_id, messages=[ChatMessageSchema(**m) for m in messages]
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve history: {str(e)}",
        ) from e


@router.delete("/session/{session_id}", status_code=status.HTTP_200_OK)
async def delete_history(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
):
    try:
        await clear_session(session_id=session_id, db=db, redis_client=redis_client)
        return {"status": "cleared", "session_id": session_id}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to clear history: {str(e)}",
        ) from e
