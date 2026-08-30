import datetime
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


# Cart Schemas (persisted in Redis as key-value objects)
class CartItem(BaseModel):
    sku: str = Field(..., max_length=50, description="SKU of the product in the cart")
    quantity: int = Field(..., gt=0, description="Quantity of the product")


class CartRead(BaseModel):
    customer_id: int
    items: list[CartItem]


# Order Item Schemas
class OrderItemCreate(BaseModel):
    product_id: uuid.UUID
    quantity: int = Field(..., gt=0)
    unit_price: Decimal = Field(..., gt=0)


class OrderItemRead(OrderItemCreate):
    id: int
    order_id: uuid.UUID

    model_config = ConfigDict(from_attributes=True)


# Order Schemas
class OrderCreate(BaseModel):
    customer_id: int
    shipping_address: str = Field(
        ..., max_length=500, description="Destination shipping address"
    )


class OrderRead(BaseModel):
    id: uuid.UUID
    customer_id: int
    status: str
    total_amount: Decimal
    shipping_address: str
    created_at: datetime.datetime
    items: list[OrderItemRead]

    model_config = ConfigDict(from_attributes=True)
