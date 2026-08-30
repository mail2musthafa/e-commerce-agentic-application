import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from services.catalog.models import Category, Product
from services.catalog.schemas import (
    CategoryCreate,
    CategoryRead,
    ProductCreate,
    ProductRead,
)
from services.database import get_db

router = APIRouter(prefix="/catalog", tags=["Catalog"])


@router.post(
    "/categories", response_model=CategoryRead, status_code=status.HTTP_201_CREATED
)
async def create_category(
    category_in: CategoryCreate, db: AsyncSession = Depends(get_db)
):
    # Check if category slug already exists to prevent duplicate indexes
    query = select(Category).where(Category.slug == category_in.slug)
    result = await db.execute(query)
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Category slug '{category_in.slug}' already exists",
        )
    category = Category(**category_in.model_dump())
    db.add(category)
    await db.commit()
    await db.refresh(category)
    return category


@router.get("/categories", response_model=list[CategoryRead])
async def list_categories(db: AsyncSession = Depends(get_db)):
    query = select(Category)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.post(
    "/products", response_model=ProductRead, status_code=status.HTTP_201_CREATED
)
async def create_product(product_in: ProductCreate, db: AsyncSession = Depends(get_db)):
    # Check if SKU is unique
    query = select(Product).where(Product.sku == product_in.sku)
    result = await db.execute(query)
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Product with SKU '{product_in.sku}' already exists",
        )
    # Check if category exists
    cat_query = select(Category).where(Category.id == product_in.category_id)
    cat_res = await db.execute(cat_query)
    if not cat_res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Category with ID {product_in.category_id} not found",
        )

    product = Product(**product_in.model_dump())
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return product


@router.get("/products", response_model=list[ProductRead])
async def list_products(
    category_id: int | None = None, db: AsyncSession = Depends(get_db)
):
    query = select(Product)
    if category_id is not None:
        query = query.where(Product.category_id == category_id)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/products/{product_id}", response_model=ProductRead)
async def get_product(product_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    query = select(Product).where(Product.id == product_id)
    result = await db.execute(query)
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with ID {product_id} not found",
        )
    return product
