import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from services.catalog.models import Category, Product
from services.customers.models import Customer

# Import all models to register them on the Base metadata for autogenerate detection
from services.database import DATABASE_URL, Base
from services.inventory.models import InventoryItem
from services.knowledge.models import KnowledgeChunk
from services.memory.models import ConversationMessage
from services.orders.models import Order, OrderItem
from services.payments.models import Transaction
from services.shipping.models import Shipment

# Reference models to prevent unused-import pruning by formatters
_ = [
    Category,
    Product,
    InventoryItem,
    Customer,
    Order,
    OrderItem,
    Transaction,
    Shipment,
    KnowledgeChunk,
    ConversationMessage,
]

# Interpret the config file for Python logging
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = DATABASE_URL
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    # Create an async engine using the application connection string
    connectable = create_async_engine(
        DATABASE_URL,
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
