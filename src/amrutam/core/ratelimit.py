"""App-level fixed-window rate limit (Redis). Edge Nginx does coarse limit.

Fail-open on Redis outage: availability beats strict throttling (edge Nginx
still throttles; `redis down` alert covers the abuse window). Auth endpoints
could opt into fail-closed; booking/payments stay available.
"""

from __future__ import annotations

import logging
from typing import Any

from amrutam.core.errors import RateLimited

log = logging.getLogger(__name__)


async def check_rate_limit(redis: Any, key: str, limit: int = 60, window_s: int = 60) -> None:
    try:
        count = await redis.incr(f"rl:{key}")
        if count == 1:
            await redis.expire(f"rl:{key}", window_s)
    except Exception as e:  # noqa: BLE001 — fail open, alert fires
        log.warning("rate limit skipped (redis down): %s", e)
        return
    if count > limit:
        raise RateLimited(f"rate limit exceeded ({limit}/{window_s}s)")
