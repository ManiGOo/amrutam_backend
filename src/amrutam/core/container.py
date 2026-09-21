"""Lightweight DI container — singleton built in lifespan startup."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from amrutam.core.config import Settings


class Container:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._engine = create_async_engine(
            settings.database_url,
            pool_size=20,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=1800,
        )
        self._replica_engine = create_async_engine(
            settings.replica_database_url,
            pool_size=10,
            max_overflow=5,
            pool_pre_ping=True,
            pool_recycle=1800,
        )
        self._session_factory = async_sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )
        self._replica_session_factory = async_sessionmaker(
            self._replica_engine, class_=AsyncSession, expire_on_commit=False
        )
        self._redis: Redis[Any] | None = None

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self._session_factory() as s:
            yield s  # caller (use case) owns commit/rollback

    @asynccontextmanager
    async def replica_session(self) -> AsyncIterator[AsyncSession]:
        async with self._replica_session_factory() as s:
            yield s

    async def get_redis(self) -> Redis[Any]:
        if self._redis is None:
            redis: Redis[Any] = Redis.from_url(self.settings.redis_url, decode_responses=True)
            self._redis = redis
        assert self._redis is not None
        return self._redis

    async def health(self) -> dict[str, str]:
        from sqlalchemy import text

        out: dict[str, str] = {}
        try:
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            out["postgres_primary"] = "up"
        except Exception as e:  # noqa: BLE001
            out["postgres_primary"] = f"down: {e}"
        try:
            r = await self.get_redis()
            await r.ping()
            out["redis"] = "up"
        except Exception as e:  # noqa: BLE001
            out["redis"] = f"down: {e}"
        return out

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()  # type: ignore[attr-defined]
        await self._engine.dispose()
        await self._replica_engine.dispose()
