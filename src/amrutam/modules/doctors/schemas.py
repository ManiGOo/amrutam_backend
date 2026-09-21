from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DoctorOut(BaseModel):
    id: str
    full_name: str | None = None
    specialization: str


class SlotCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    starts_at: datetime
    ends_at: datetime


class SlotOut(BaseModel):
    id: str
    doctor_id: str
    starts_at: datetime
    ends_at: datetime
    status: str
    version: int
