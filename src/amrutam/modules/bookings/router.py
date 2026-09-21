from typing import Any

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy.ext.asyncio import AsyncSession

from amrutam.api.deps import AuthUser, get_redis, get_session, require_role
from amrutam.core.errors import BadRequest
from amrutam.core.ratelimit import check_rate_limit
from amrutam.modules.bookings import service
from amrutam.modules.bookings.schemas import BookingCreate, BookingResponse

router = APIRouter(prefix="/v1/bookings", tags=["bookings"])


@router.post("", response_model=BookingResponse, status_code=202)
async def create_booking(
    payload: BookingCreate,
    response: Response,
    patient: AuthUser = Depends(require_role("patient")),
    db: AsyncSession = Depends(get_session),
    redis: Any = Depends(get_redis),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> BookingResponse:
    if not idempotency_key:
        raise BadRequest("Idempotency-Key header is required")
    await check_rate_limit(redis, f"booking:{patient.id}", limit=30, window_s=60)
    body, _replayed = await service.handle_booking(
        db, redis, patient.id, payload.slot_id, idempotency_key
    )
    response.headers["Location"] = f"/v1/consultations/{body['id']}"
    return BookingResponse(**body)
