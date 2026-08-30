import logging
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from services.catalog.models import Product
from services.inventory.models import InventoryItem

logger = logging.getLogger("a2a")


class A2AMessage(BaseModel):
    sender: str = Field(
        ..., description="The name of the sender agent initiating the message"
    )
    receiver: str = Field(
        ..., description="The name of the target agent receiving the message"
    )
    method: str = Field(..., description="The JSON-RPC method to invoke")
    params: dict[str, Any] = Field(
        ..., description="Parameters required for the method call"
    )
    id: str = Field(
        ..., description="Correlation request ID matching requests and responses"
    )


class A2AResponse(BaseModel):
    id: str
    result: dict[str, Any] | None = None
    error: str | None = None


class A2ADispatcher:
    async def dispatch(self, message: A2AMessage, db: AsyncSession) -> A2AResponse:
        """Parses inter-agent messages and invokes downstream service handlers on designated receiver agents."""
        logger.info(
            f"A2A dispatch: {message.sender} -> {message.receiver} [Method: {message.method}]"
        )

        if message.receiver == "InventoryAgent":
            return await self._handle_inventory(message, db)
        else:
            logger.warning(
                f"A2A dispatch failed: Receiver '{message.receiver}' is not registered."
            )
            return A2AResponse(
                id=message.id,
                error=f"Receiver Agent '{message.receiver}' is not registered",
            )

    async def _handle_inventory(
        self, message: A2AMessage, db: AsyncSession
    ) -> A2AResponse:
        if message.method == "request_restock":
            sku = message.params.get("sku")
            quantity = message.params.get("quantity", 1)

            if not sku:
                return A2AResponse(
                    id=message.id, error="Missing required parameter 'sku'"
                )

            # Find product matching SKU
            prod_stmt = select(Product).where(Product.sku == sku)
            prod_res = await db.execute(prod_stmt)
            product = prod_res.scalar_one_or_none()
            if not product:
                return A2AResponse(
                    id=message.id, error=f"Product with SKU '{sku}' not found"
                )

            # Find inventory item matching product id
            inv_stmt = select(InventoryItem).where(
                InventoryItem.product_id == product.id
            )
            inv_res = await db.execute(inv_stmt)
            inventory = inv_res.scalar_one_or_none()
            if not inventory:
                return A2AResponse(
                    id=message.id,
                    error=f"Inventory record for product '{sku}' not found",
                )

            # Restock warehouse quantity
            inventory.quantity += quantity
            await db.commit()

            logger.info(
                f"Inventory restocked SKU '{sku}' with {quantity} units. New quantity: {inventory.quantity}"
            )

            return A2AResponse(
                id=message.id,
                result={
                    "status": "success",
                    "sku": sku,
                    "new_quantity": inventory.quantity,
                    "warehouse": inventory.warehouse,
                },
            )
        else:
            return A2AResponse(
                id=message.id,
                error=f"Method '{message.method}' not supported by receiver '{message.receiver}'",
            )
