"""Doctor search served from the read replica (GIN trigram index)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def search_doctors(
    db: AsyncSession,
    q: str | None = None,
    specialization: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> list[dict[str, Any]]:
    clauses = ["1=1"]
    params: dict[str, Any] = {"l": limit}
    if q:
        clauses.append(
            "(d.specialization ILIKE :q OR d.specialization % :qq OR p.full_name ILIKE :q)"
        )
        params["q"] = f"%{q}%"
        params["qq"] = q
    if specialization:
        clauses.append("d.specialization ILIKE :s")
        params["s"] = f"%{specialization}%"
    if cursor:
        clauses.append("d.user_id::text > :c")
        params["c"] = cursor
    where = " AND ".join(clauses)
    # where is assembled from static fragments only; user input stays in bound params
    stmt = (
        "SELECT d.user_id::text, p.full_name, d.specialization "  # noqa: S608
        "FROM doctors d LEFT JOIN profiles p ON p.user_id = d.user_id "
        f"WHERE {where} ORDER BY d.user_id LIMIT :l"
    )
    rows = (await db.execute(text(stmt), params)).all()
    return [{"id": r[0], "full_name": r[1], "specialization": r[2]} for r in rows]
