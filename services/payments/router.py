import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from services.database import get_db
from services.inventory.models import InventoryItem
from services.orders.models import Order
from services.payments.models import Transaction
from services.payments.schemas import PaymentProcess, TransactionRead

router = APIRouter(prefix="/payments", tags=["Payments"])


@router.post("/charge", response_model=TransactionRead)
async def charge_payment(payload: PaymentProcess, db: AsyncSession = Depends(get_db)):
    # 1. Fetch Order with items eagerly loaded
    query = (
        select(Order)
        .options(selectinload(Order.items))
        .where(Order.id == payload.order_id)
    )
    result = await db.execute(query)
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order with ID {payload.order_id} not found",
        )

    if order.status != "PENDING":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Order is already in state '{order.status}' and cannot be charged.",
        )

    # 2. Simulate payment validation (fails if card number ends in '0000')
    tx_status = "SUCCESS"
    if payload.card_number.endswith("0000"):
        tx_status = "FAILED"

    tx_ref = f"TXN-{secrets.token_hex(6).upper()}"

    # 3. Create Transaction record
    transaction = Transaction(
        order_id=order.id,
        payment_method=payload.payment_method,
        status=tx_status,
        amount=order.total_amount,
        transaction_ref=tx_ref,
    )
    db.add(transaction)

    # 4. Handle success/failure states
    if tx_status == "SUCCESS":
        order.status = "PAID"

        # Deduct reserved stocks physically from the warehouse levels
        for item in order.items:
            inv_query = select(InventoryItem).where(
                InventoryItem.product_id == item.product_id
            )
            inv_res = await db.execute(inv_query)
            inventory = inv_res.scalar_one_or_none()
            if inventory:
                inventory.quantity -= item.quantity
                inventory.reserved_quantity -= item.quantity
    else:
        # Keep order pending to allow card retry
        order.status = "PENDING"

    await db.commit()
    await db.refresh(transaction)
    return transaction
