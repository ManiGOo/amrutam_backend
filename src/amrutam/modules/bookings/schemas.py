from pydantic import BaseModel, ConfigDict, Field


class BookingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot_id: str = Field(min_length=8, max_length=64)


class BookingResponse(BaseModel):
    id: str
    status: str
    slot_id: str
