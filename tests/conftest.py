"""Shared fixtures: localhost PG + Redis (already up via docker compose)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from amrutam.core.config import Settings, get_settings


def test_settings() -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://amrutam:amrutam@localhost:5432/amrutam",
        replica_database_url="postgresql+asyncpg://amrutam:amrutam@localhost:5432/amrutam",
        redis_url="redis://localhost:6379/0",
    )


@pytest.fixture()
def settings() -> Settings:
    return test_settings()


@pytest_asyncio.fixture()
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "postgresql+asyncpg://amrutam:amrutam@localhost:5432/amrutam",
        pool_size=10,
        max_overflow=10,
    )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture()
async def redis_client() -> AsyncIterator[Any]:
    r: Any = Redis.from_url("redis://localhost:6379/0", decode_responses=True)
    yield r
    await r.aclose()


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@example.com"


# Make get_settings() return localhost settings inside service calls that
# default to it (security helpers). Auth router passes explicit settings.
@pytest.fixture(autouse=True)
def _patch_settings(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    import amrutam.api.deps as deps

    get_settings.cache_clear()
    deps.reset_container()  # engines are loop-bound; never reuse across tests
    monkeypatch.setattr("amrutam.core.config.get_settings", lambda: settings)
    # modules that imported get_settings by reference — patch there too
    import amrutam.core.security as sec

    monkeypatch.setattr(sec, "get_settings", lambda: settings)
    monkeypatch.setattr(deps, "get_settings", lambda: settings)
    yield
    deps.reset_container()
    get_settings.cache_clear()
