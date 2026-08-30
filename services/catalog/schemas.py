import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


# Category Schemas
class CategoryBase(BaseModel):
    name: str = Field(
        ..., max_length=100, description="The display name of the category"
    )
    slug: str = Field(..., max_length=100, description="URL-friendly identifier")


class CategoryCreate(CategoryBase):
    pass


class CategoryRead(CategoryBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


# Product Schemas
class ProductBase(BaseModel):
    sku: str = Field(..., max_length=50, description="Unique Stock Keeping Unit code")
    name: str = Field(..., max_length=200, description="Name of the product")
    description: str | None = Field(
        None, max_length=1000, description="Detailed product description"
    )
    price: Decimal = Field(
        ..., gt=0, description="Unit price, must be greater than zero"
    )
    category_id: int = Field(..., description="ID of the parent category")


class ProductCreate(ProductBase):
    pass


class ProductRead(ProductBase):
    id: uuid.UUID

    model_config = ConfigDict(from_attributes=True)
