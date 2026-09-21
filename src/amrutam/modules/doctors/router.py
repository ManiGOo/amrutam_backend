from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from amrutam.api.deps import AuthUser, get_session, require_role
from amrutam.modules.doctors import service
from amrutam.modules.doctors.schemas import DoctorOut, SlotCreate, SlotOut

router = APIRouter(prefix="/v1/doctors", tags=["doctors"])


@router.get("", response_model=list[DoctorOut])
async def list_doctors(
    specialization: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=20, le=100),
    db: AsyncSession = Depends(get_session),
) -> list[DoctorOut]:
    rows = await service.list_doctors(db, specialization, limit)
    return [DoctorOut(**r) for r in rows]


@router.post("/slots", response_model=SlotOut, status_code=201)
async def create_slot(
    payload: SlotCreate,
    user: AuthUser = Depends(require_role("doctor", "admin")),
    db: AsyncSession = Depends(get_session),
) -> SlotOut:
    row = await service.create_slot(db, user.id, payload.starts_at, payload.ends_at)
    return SlotOut(**row)


@router.get("/{doctor_id}/slots", response_model=list[SlotOut])
async def list_slots(
    doctor_id: str,
    status: str | None = Query(default=None, max_length=20),
    db: AsyncSession = Depends(get_session),
) -> list[SlotOut]:
    rows = await service.list_slots(db, doctor_id, status)
    return [SlotOut(**r) for r in rows]
