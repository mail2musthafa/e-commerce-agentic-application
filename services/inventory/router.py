from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from services.catalog.models import Product
from services.database import get_db
from services.inventory.models import InventoryItem
from services.inventory.schemas import InventoryRead, InventoryReserve, InventoryRestock

router = APIRouter(prefix="/inventory", tags=["Inventory"])


@router.get("/{sku}", response_model=InventoryRead)
async def get_inventory(sku: str, db: AsyncSession = Depends(get_db)):
    query = select(InventoryItem).where(InventoryItem.sku == sku)
    result = await db.execute(query)
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inventory item for SKU '{sku}' not found",
        )
    return item


@router.post("/restock", response_model=InventoryRead)
async def restock_inventory(
    payload: InventoryRestock, db: AsyncSession = Depends(get_db)
):
    # Verify product exists in the catalog before restocking
    prod_query = select(Product).where(Product.sku == payload.sku)
    prod_res = await db.execute(prod_query)
    product = prod_res.scalar_one_or_none()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with SKU '{payload.sku}' does not exist in catalog",
        )

    # Check if inventory item already exists
    inv_query = select(InventoryItem).where(InventoryItem.sku == payload.sku)
    inv_res = await db.execute(inv_query)
    item = inv_res.scalar_one_or_none()

    if item:
        item.quantity += payload.quantity
    else:
        item = InventoryItem(
            product_id=product.id,
            sku=product.sku,
            quantity=payload.quantity,
            reserved_quantity=0,
            warehouse=payload.warehouse,
        )
        db.add(item)

    await db.commit()
    await db.refresh(item)
    return item


@router.post("/reserve", response_model=InventoryRead)
async def reserve_inventory(
    payload: InventoryReserve, db: AsyncSession = Depends(get_db)
):
    query = select(InventoryItem).where(InventoryItem.sku == payload.sku)
    result = await db.execute(query)
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inventory item for SKU '{payload.sku}' not found",
        )

    if item.available_quantity < payload.quantity:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient inventory for SKU '{payload.sku}'. Available: {item.available_quantity}, Requested: {payload.quantity}",
        )

    item.reserved_quantity += payload.quantity
    await db.commit()
    await db.refresh(item)
    return item


@router.post("/release", response_model=InventoryRead)
async def release_inventory(
    payload: InventoryReserve, db: AsyncSession = Depends(get_db)
):
    query = select(InventoryItem).where(InventoryItem.sku == payload.sku)
    result = await db.execute(query)
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inventory item for SKU '{payload.sku}' not found",
        )

    if item.reserved_quantity < payload.quantity:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot release {payload.quantity} units; only {item.reserved_quantity} units are currently reserved.",
        )

    item.reserved_quantity -= payload.quantity
    await db.commit()
    await db.refresh(item)
    return item
