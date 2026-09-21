from typing import Any

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from amrutam.api.deps import AuthUser, get_redis, get_session, require_role
from amrutam.core.config import Settings, get_settings
from amrutam.core.errors import BadRequest, Unauthorized
from amrutam.core.ratelimit import check_rate_limit
from amrutam.modules.payments import service
from amrutam.modules.payments.schemas import PaymentCreate, PaymentOut, WebhookPayload

router = APIRouter(prefix="/v1/payments", tags=["payments"])


@router.post("", response_model=PaymentOut, status_code=202)
async def create_payment(
    payload: PaymentCreate,
    user: AuthUser = Depends(require_role("patient", "admin")),
    db: AsyncSession = Depends(get_session),
    redis: Any = Depends(get_redis),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> PaymentOut:
    if not idempotency_key:
        raise BadRequest("Idempotency-Key header is required")
    await check_rate_limit(redis, f"pay:{user.id}", limit=30, window_s=60)
    out = await service.create_intent(
        db,
        redis,
        user,
        payload.consultation_id,
        payload.amount,
        payload.currency,
        payload.force_fail,
        idempotency_key,
    )
    return PaymentOut(**out)


@router.post("/webhook", response_model=PaymentOut)
async def webhook(
    payload: WebhookPayload,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    secret: str | None = Header(default=None, alias="X-Webhook-Secret"),
) -> PaymentOut:
    if secret != settings.payment_webhook_secret:
        raise Unauthorized("bad webhook secret")
    out = await service.apply_webhook(
        db, payload.consultation_id, payload.status, payload.gateway_ref
    )
    return PaymentOut(**out)
