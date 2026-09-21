"""Mock payment gateway — deterministic, idempotent by key.

Real prod would call Razorpay/Stripe here. The mock succeeds for amount > 0
unless `force_fail` is set, letting tests drive both saga branches.
"""

from __future__ import annotations

import hashlib


async def charge(
    consultation_id: str, amount: int, idempotency_key: str, force_fail: bool = False
) -> dict[str, str | bool]:
    ref = "mock_" + hashlib.sha256(f"{consultation_id}:{idempotency_key}".encode()).hexdigest()[:16]
    if force_fail or amount <= 0:
        return {"ok": False, "gateway_ref": ref}
    return {"ok": True, "gateway_ref": ref}
