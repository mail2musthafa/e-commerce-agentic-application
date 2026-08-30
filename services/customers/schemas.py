from pydantic import BaseModel, ConfigDict, Field


class CustomerBase(BaseModel):
    email: str = Field(
        ..., max_length=100, description="Customer primary email address"
    )
    name: str = Field(..., max_length=100, description="Customer display name")
    shipping_address: str | None = Field(
        None, max_length=500, description="Default shipping address"
    )


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    name: str | None = Field(
        None, max_length=100, description="Update customer display name"
    )
    shipping_address: str | None = Field(
        None, max_length=500, description="Update default shipping address"
    )


class CustomerRead(CustomerBase):
    id: int

    model_config = ConfigDict(from_attributes=True)
