from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from amrutam.api.deps import AuthUser, get_current_user, get_session
from amrutam.modules.consultations import service
from amrutam.modules.consultations.schemas import ConsultationOut, TransitionRequest

router = APIRouter(prefix="/v1/consultations", tags=["consultations"])


@router.get("", response_model=list[ConsultationOut])
async def list_mine(
    limit: int = Query(default=20, le=100),
    cursor: str | None = Query(default=None),
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> list[ConsultationOut]:
    rows = await service.list_mine(db, user, limit, cursor)
    return [ConsultationOut(**r) for r in rows]


@router.get("/{cid}", response_model=ConsultationOut)
async def get_one(
    cid: str,
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> ConsultationOut:
    return ConsultationOut(**await service.get_consultation(db, cid, user))


@router.post("/{cid}/transition", response_model=ConsultationOut)
async def transition(
    cid: str,
    payload: TransitionRequest,
    user: AuthUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> ConsultationOut:
    return ConsultationOut(**await service.transition(db, cid, user, payload.action))
