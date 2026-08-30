from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from services.customers.models import Customer
from services.customers.schemas import CustomerCreate, CustomerRead, CustomerUpdate
from services.database import get_db

router = APIRouter(prefix="/customers", tags=["Customers"])


@router.post("", response_model=CustomerRead, status_code=status.HTTP_201_CREATED)
async def create_customer(payload: CustomerCreate, db: AsyncSession = Depends(get_db)):
    # Check if customer already registered
    query = select(Customer).where(Customer.email == payload.email)
    result = await db.execute(query)
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Customer with email '{payload.email}' already exists",
        )
    customer = Customer(**payload.model_dump())
    db.add(customer)
    await db.commit()
    await db.refresh(customer)
    return customer


@router.get("/{email}", response_model=CustomerRead)
async def get_customer(email: str, db: AsyncSession = Depends(get_db)):
    query = select(Customer).where(Customer.email == email)
    result = await db.execute(query)
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Customer with email '{email}' not found",
        )
    return customer


@router.put("/{email}", response_model=CustomerRead)
async def update_customer(
    email: str, payload: CustomerUpdate, db: AsyncSession = Depends(get_db)
):
    query = select(Customer).where(Customer.email == email)
    result = await db.execute(query)
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Customer with email '{email}' not found",
        )

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(customer, key, value)

    await db.commit()
    await db.refresh(customer)
    return customer
