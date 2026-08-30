import json
import uuid

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from services.catalog.models import Product
from services.customers.models import Customer
from services.database import get_db, get_redis
from services.inventory.models import InventoryItem
from services.orders.models import Order, OrderItem
from services.orders.schemas import CartItem, CartRead, OrderCreate, OrderRead

router = APIRouter(prefix="/orders", tags=["Orders"])


# Helper to format redis cart keys
def get_cart_key(customer_id: int) -> str:
    return f"cart:{customer_id}"


@router.post("/cart/{customer_id}", response_model=CartRead)
async def update_cart(
    customer_id: int,
    items: list[CartItem],
    r: redis.Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
):
    # Verify customer exists before updating cart
    cust_query = select(Customer).where(Customer.id == customer_id)
    cust_res = await db.execute(cust_query)
    if not cust_res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Customer with ID {customer_id} not found",
        )

    # Store cart in Redis as serialized JSON
    cart_data = [item.model_dump() for item in items]
    await r.set(get_cart_key(customer_id), json.dumps(cart_data))
    return CartRead(customer_id=customer_id, items=items)


@router.get("/cart/{customer_id}", response_model=CartRead)
async def get_cart(customer_id: int, r: redis.Redis = Depends(get_redis)):
    raw_cart = await r.get(get_cart_key(customer_id))
    if not raw_cart:
        return CartRead(customer_id=customer_id, items=[])
    items = json.loads(raw_cart)
    return CartRead(customer_id=customer_id, items=[CartItem(**item) for item in items])


@router.delete("/cart/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def empty_cart(customer_id: int, r: redis.Redis = Depends(get_redis)):
    await r.delete(get_cart_key(customer_id))


@router.post("/checkout", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
async def checkout(
    payload: OrderCreate,
    db: AsyncSession = Depends(get_db),
    r: redis.Redis = Depends(get_redis),
):
    # 1. Verify Customer exists
    cust_query = select(Customer).where(Customer.id == payload.customer_id)
    cust_res = await db.execute(cust_query)
    customer = cust_res.scalar_one_or_none()
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Customer with ID {payload.customer_id} not found",
        )

    # 2. Get active shopping cart items from Redis
    raw_cart = await r.get(get_cart_key(payload.customer_id))
    if not raw_cart:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Shopping cart is empty"
        )
    cart_items = [CartItem(**item) for item in json.loads(raw_cart)]
    if not cart_items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Shopping cart is empty"
        )

    # 3. Process cart items, verify stock availability, and calculate order totals
    order_items_to_create = []
    total_amount = 0

    for item in cart_items:
        # Fetch Product
        prod_query = select(Product).where(Product.sku == item.sku)
        prod_res = await db.execute(prod_query)
        product = prod_res.scalar_one_or_none()
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product with SKU '{item.sku}' in cart was not found in catalog",
            )

        # Verify inventory stock levels and reserve quantity
        inv_query = select(InventoryItem).where(InventoryItem.product_id == product.id)
        inv_res = await db.execute(inv_query)
        inventory = inv_res.scalar_one_or_none()
        if not inventory or inventory.available_quantity < item.quantity:
            available = inventory.available_quantity if inventory else 0
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient inventory for SKU '{item.sku}'. Available: {available}, Requested: {item.quantity}",
            )

        # Increment reserved quantity to block double reservation
        inventory.reserved_quantity += item.quantity

        # Calculate subtotal
        item_total = product.price * item.quantity
        total_amount += item_total

        order_items_to_create.append(
            OrderItem(
                product_id=product.id, quantity=item.quantity, unit_price=product.price
            )
        )

    # 4. Create database Order record
    order = Order(
        customer_id=payload.customer_id,
        status="PENDING",
        total_amount=total_amount,
        shipping_address=payload.shipping_address,
        items=order_items_to_create,
    )
    db.add(order)
    await db.commit()

    # Eagerly load the order and its items relationship before returning it to serialisation
    query = select(Order).options(selectinload(Order.items)).where(Order.id == order.id)
    result = await db.execute(query)
    order = result.scalar_one()

    # 5. Clear Redis Cart upon checkout success
    await r.delete(get_cart_key(payload.customer_id))

    return order


@router.get("/{order_id}", response_model=OrderRead)
async def get_order(order_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    # Eagerly load relationship to prevent lazy-load exceptions
    query = select(Order).options(selectinload(Order.items)).where(Order.id == order_id)
    result = await db.execute(query)
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order with ID {order_id} not found",
        )
    return order
