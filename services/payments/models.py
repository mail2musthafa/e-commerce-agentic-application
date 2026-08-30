import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from services.database import Base


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    payment_method: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # E.g., Card, Paypal
    status: Mapped[str] = mapped_column(String(50), nullable=False)  # SUCCESS, FAILED
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    transaction_ref: Mapped[str] = mapped_column(
        String(100), unique=True, index=True, nullable=False
    )
