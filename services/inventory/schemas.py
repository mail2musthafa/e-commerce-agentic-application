import uuid

from pydantic import BaseModel, ConfigDict, Field


class InventoryRead(BaseModel):
    product_id: uuid.UUID
    sku: str
    quantity: int
    reserved_quantity: int
    available_quantity: int
    warehouse: str

    model_config = ConfigDict(from_attributes=True)


class InventoryRestock(BaseModel):
    sku: str = Field(..., max_length=50, description="SKU of the product to restock")
    quantity: int = Field(..., gt=0, description="Quantity to add to the inventory")
    warehouse: str = Field(
        "Main Warehouse", max_length=100, description="Target warehouse name"
    )


class InventoryReserve(BaseModel):
    sku: str = Field(..., max_length=50, description="SKU to reserve")
    quantity: int = Field(..., gt=0, description="Quantity to reserve")
