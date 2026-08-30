import asyncio

from sqlalchemy import text

from services.database import async_session


async def reset():
    async with async_session() as session:
        await session.execute(
            text("UPDATE inventory_items SET quantity = 50, reserved_quantity = 0")
        )
        await session.commit()
    print("Warehouse stock levels reset to 50 units.")


if __name__ == "__main__":
    asyncio.run(reset())
