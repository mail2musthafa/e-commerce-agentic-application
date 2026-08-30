import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class PaymentProcess(BaseModel):
    order_id: uuid.UUID
    payment_method: str = Field("Credit Card", max_length=50)
    card_number: str = Field(
        ..., min_length=15, max_length=19, description="Dummy credit card number"
    )


class TransactionRead(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    payment_method: str
    status: str
    amount: Decimal
    transaction_ref: str

    model_config = ConfigDict(from_attributes=True)
