from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from amrutam.api.deps import AuthUser, get_replica_session, require_role
from amrutam.modules.analytics import service


class DailyRow(BaseModel):
    day: str
    status: str
    n: int


class FunnelRow(BaseModel):
    status: str
    n: int


router = APIRouter(prefix="/v1/analytics", tags=["analytics"])


@router.get("/daily", response_model=list[DailyRow])
async def daily(
    limit: int = Query(default=30, le=365),
    _: AuthUser = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_replica_session),
) -> list[DailyRow]:
    return [DailyRow(**r) for r in await service.daily(db, limit)]


@router.get("/funnel", response_model=list[FunnelRow])
async def funnel(
    _: AuthUser = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_replica_session),
) -> list[FunnelRow]:
    return [FunnelRow(**r) for r in await service.funnel(db)]
