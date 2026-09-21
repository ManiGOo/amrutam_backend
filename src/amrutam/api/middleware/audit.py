"""Chain-hash audit middleware: append-only row on every mutation (best-effort).

Uses the shared write_audit helper (advisory-locked, fork-free).
Table-level REVOKE UPDATE/DELETE (applied in prod grants) makes it tamper-evident.
"""

from __future__ import annotations

from datetime import UTC, datetime

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from amrutam.core.audit import write_audit

SKIP_PREFIXES = ("/health", "/ready", "/docs", "/redoc", "/openapi.json")


def _should_audit(request: Request) -> bool:
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return False
    return not request.url.path.startswith(SKIP_PREFIXES)


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        if not _should_audit(request):
            return response
        try:
            container = request.app.state.container
        except AttributeError:
            return response
        try:
            actor = "anonymous"
            auth = request.headers.get("authorization", "")
            if auth.startswith("Bearer "):
                from amrutam.core import security

                try:
                    claims = security.decode_token(auth[7:])
                    actor = str(claims.get("sub", "anonymous"))
                except Exception:
                    actor = "invalid-token"
            async with container.session() as db:
                async with db.begin():
                    await write_audit(
                        db,
                        actor=actor,
                        action=f"{request.method} {request.url.path}",
                        entity="http",
                        entity_id=request.url.path,
                        payload={
                            "status": response.status_code,
                            "ts": datetime.now(UTC).isoformat(),
                        },
                    )
        except Exception as e:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).debug("audit write skipped: %s", e)
        return response
