from pydantic import BaseModel, ConfigDict, Field


class PrescriptionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diagnosis: str = Field(min_length=1, max_length=2000)
    medicines: list[str] = Field(min_length=1, max_length=50)


class PrescriptionOut(BaseModel):
    id: str
    consultation_id: str


class PrescriptionView(BaseModel):
    id: str
    consultation_id: str
    diagnosis: str
    medicines: list[str]


class PdfUrl(BaseModel):
    url: str
    expires_in_s: int = 300
