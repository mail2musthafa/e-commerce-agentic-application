import os
import sys
from collections.abc import AsyncGenerator

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

# Database configuration
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://commerce_user:commerce_secure_password_99@localhost:5432/commerce_db",
)

# Detect if running under pytest to disable pooling and prevent event loop issues
is_testing = "pytest" in sys.modules or os.getenv("TESTING") == "1"

# Create the async SQLAlchemy engine dynamically
engine_kwargs = {"echo": False}
if is_testing:
    engine_kwargs["poolclass"] = NullPool
else:
    engine_kwargs.update({"pool_size": 10, "max_overflow": 20, "pool_pre_ping": True})

engine = create_async_engine(DATABASE_URL, **engine_kwargs)

# Async session factory
async_session = async_sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)

# Redis configuration (defaults to the redis container ports mapped locally)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)


# Declarative base model class
class Base(DeclarativeBase):
    pass


# FastAPI Dependency to retrieve active db sessions in endpoints
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


# Dependency to retrieve redis connection instance
async def get_redis() -> AsyncGenerator[redis.Redis, None]:
    if is_testing:
        # Create a fresh Redis client for each request context during tests
        client = redis.from_url(REDIS_URL, decode_responses=True)
        try:
            yield client
        finally:
            await client.aclose()
    else:
        yield redis_client
