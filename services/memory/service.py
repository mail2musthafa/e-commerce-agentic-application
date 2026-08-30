import json
import logging

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from services.memory.models import ConversationMessage

logger = logging.getLogger("memory_service")

# Session cache TTL in Redis (1 hour)
REDIS_SESSION_TTL = 3600


def truncate_messages(messages: list[dict], max_tokens: int = 2000) -> list[dict]:
    """Prunes messages to fit within token limits, preserving system instructions at index 0."""
    if not messages:
        return []

    system_msg = None
    other_msgs = []

    for msg in messages:
        if msg.get("role") == "system":
            system_msg = msg
        else:
            other_msgs.append(msg)

    # Approximating token length using character heuristics: characters / 4
    while other_msgs:
        total_tokens = sum(len(m.get("content", "")) // 4 for m in other_msgs)
        if system_msg:
            total_tokens += len(system_msg.get("content", "")) // 4

        if total_tokens <= max_tokens:
            break
        # Remove oldest non-system message
        other_msgs.pop(0)

    if system_msg:
        return [system_msg] + other_msgs
    return other_msgs


async def add_message(
    session_id: str, role: str, content: str, db: AsyncSession, redis_client
) -> ConversationMessage:
    """Saves a chat message in PostgreSQL database and appends to Redis short-term cache."""
    # 1. Persist to Postgres
    db_msg = ConversationMessage(session_id=session_id, role=role, content=content)
    db.add(db_msg)
    await db.commit()

    # 2. Update Redis Cache
    redis_key = f"session:{session_id}"
    try:
        cached = await redis_client.get(redis_key)
        if cached:
            messages = json.loads(cached)
            messages.append({"role": role, "content": content})
        else:
            # Rehydrate from DB if cache was missing
            stmt = (
                select(ConversationMessage)
                .where(ConversationMessage.session_id == session_id)
                .order_by(ConversationMessage.created_at.asc())
            )
            res = await db.execute(stmt)
            messages = [
                {"role": m.role, "content": m.content} for m in res.scalars().all()
            ]

        # Write back to Redis with a TTL extension
        await redis_client.set(redis_key, json.dumps(messages), ex=REDIS_SESSION_TTL)
    except Exception as e:
        logger.warning(f"Failed to cache message in Redis: {e}")

    return db_msg


async def get_messages(
    session_id: str, db: AsyncSession, redis_client, max_tokens: int = 2000
) -> list[dict]:
    """Retrieves context-truncated chat history from Redis, hydrating from Postgres if needed."""
    redis_key = f"session:{session_id}"
    try:
        cached = await redis_client.get(redis_key)
        if cached:
            messages = json.loads(cached)
            return truncate_messages(messages, max_tokens)
    except Exception as e:
        logger.warning(f"Failed to read memory from Redis: {e}")

    # Cache miss or Redis error - fetch from Postgres
    stmt = (
        select(ConversationMessage)
        .where(ConversationMessage.session_id == session_id)
        .order_by(ConversationMessage.created_at.asc())
    )
    res = await db.execute(stmt)
    db_messages = res.scalars().all()

    messages = [{"role": m.role, "content": m.content} for m in db_messages]

    # Store complete session list in Redis if possible
    try:
        await redis_client.set(redis_key, json.dumps(messages), ex=REDIS_SESSION_TTL)
    except Exception as e:
        logger.warning(f"Failed to write hydrated database memory to Redis: {e}")

    return truncate_messages(messages, max_tokens)


async def clear_session(session_id: str, db: AsyncSession, redis_client):
    """Deletes conversation memory logs from both PostgreSQL and Redis cache."""
    # 1. Clear database records
    stmt = delete(ConversationMessage).where(
        ConversationMessage.session_id == session_id
    )
    await db.execute(stmt)
    await db.commit()

    # 2. Clear Redis cache
    redis_key = f"session:{session_id}"
    try:
        await redis_client.delete(redis_key)
    except Exception as e:
        logger.warning(f"Failed to delete session cache in Redis: {e}")
