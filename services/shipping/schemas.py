import datetime
import uuid

from pydantic import BaseModel, ConfigDict, Field


class ShipmentCreate(BaseModel):
    order_id: uuid.UUID
    carrier: str = Field("DHL", max_length=50, description="Logistics carrier provider")


class ShipmentRead(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    tracking_number: str
    carrier: str
    status: str
    estimated_delivery: datetime.datetime

    model_config = ConfigDict(from_attributes=True)
