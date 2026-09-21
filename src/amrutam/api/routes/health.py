from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready() -> dict[str, str]:
    # Day 1: shallow readiness. Day 2+: check PG + Redis via container.health().
    # Kept dependency-free so `pytest tests/test_health.py` passes without infra.
    return {"status": "ready"}
