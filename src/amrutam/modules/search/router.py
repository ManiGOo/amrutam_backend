from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from amrutam.api.deps import get_replica_session
from amrutam.modules.doctors.schemas import DoctorOut
from amrutam.modules.search import service

router = APIRouter(prefix="/v1/search", tags=["search"])


@router.get("/doctors", response_model=list[DoctorOut])
async def search_doctors(
    q: str | None = Query(default=None, max_length=120),
    specialization: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=20, le=100),
    cursor: str | None = Query(default=None),
    db: AsyncSession = Depends(get_replica_session),
) -> list[DoctorOut]:
    rows = await service.search_doctors(db, q, specialization, limit, cursor)
    return [DoctorOut(**r) for r in rows]
