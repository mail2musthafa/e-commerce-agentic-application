import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from services.database import get_db
from services.orders.models import Order
from services.shipping.models import Shipment
from services.shipping.schemas import ShipmentCreate, ShipmentRead

router = APIRouter(prefix="/shipping", tags=["Shipping"])


@router.post("/ship", response_model=ShipmentRead, status_code=status.HTTP_201_CREATED)
async def create_shipment(payload: ShipmentCreate, db: AsyncSession = Depends(get_db)):
    # 1. Fetch Order
    query = select(Order).where(Order.id == payload.order_id)
    result = await db.execute(query)
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order with ID {payload.order_id} not found",
        )

    # 2. Check Order is PAID
    if order.status != "PAID":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Order with ID {payload.order_id} is in state '{order.status}'. Only PAID orders can be shipped.",
        )

    # 3. Generate Tracking Number
    tracking = f"TRK-{secrets.token_hex(6).upper()}"

    # 4. Create Shipment
    shipment = Shipment(
        order_id=order.id,
        tracking_number=tracking,
        carrier=payload.carrier,
        status="SHIPPED",
    )
    db.add(shipment)

    # 5. Update Order status to SHIPPED
    order.status = "SHIPPED"

    await db.commit()
    await db.refresh(shipment)
    return shipment


@router.get("/{tracking_number}", response_model=ShipmentRead)
async def get_shipment(tracking_number: str, db: AsyncSession = Depends(get_db)):
    query = select(Shipment).where(Shipment.tracking_number == tracking_number)
    result = await db.execute(query)
    shipment = result.scalar_one_or_none()
    if not shipment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Shipment with tracking number '{tracking_number}' not found",
        )
    return shipment


@router.post("/{tracking_number}/delivery", response_model=ShipmentRead)
async def mark_delivered(tracking_number: str, db: AsyncSession = Depends(get_db)):
    # Fetch Shipment
    query = select(Shipment).where(Shipment.tracking_number == tracking_number)
    result = await db.execute(query)
    shipment = result.scalar_one_or_none()
    if not shipment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Shipment with tracking number '{tracking_number}' not found",
        )

    shipment.status = "DELIVERED"

    # Fetch corresponding Order to mark as DELIVERED
    ord_query = select(Order).where(Order.id == shipment.order_id)
    ord_res = await db.execute(ord_query)
    order = ord_res.scalar_one_or_none()
    if order:
        order.status = "DELIVERED"

    await db.commit()
    await db.refresh(shipment)
    return shipment
