from pydantic import BaseModel, ConfigDict, Field


class PaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consultation_id: str = Field(min_length=8, max_length=64)
    amount: int = Field(gt=0, le=1_000_000)
    currency: str = Field(default="INR", max_length=8)
    force_fail: bool = False


class PaymentOut(BaseModel):
    id: str
    consultation_id: str
    status: str
    gateway_ref: str | None = None


class WebhookPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consultation_id: str = Field(min_length=8, max_length=64)
    status: str = Field(pattern=r"^(paid|failed)$")
    gateway_ref: str = Field(min_length=1, max_length=128)
