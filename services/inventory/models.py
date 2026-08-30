import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from services.database import Base


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    # product_id references products.id directly (linked via cascade delete)
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), primary_key=True
    )
    sku: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reserved_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    warehouse: Mapped[str] = mapped_column(
        String(100), default="Main Warehouse", nullable=False
    )

    @property
    def available_quantity(self) -> int:
        return self.quantity - self.reserved_quantity
