from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

Transition = Literal["confirm", "start", "complete", "cancel"]


class TransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Transition


class ConsultationOut(BaseModel):
    id: str
    patient_id: str
    doctor_id: str
    slot_id: str
    status: str
    created_at: datetime
