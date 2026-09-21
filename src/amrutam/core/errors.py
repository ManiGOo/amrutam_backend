"""RFC 7807 Problem+JSON errors. One base class, subclasses per business case."""

import json
from typing import Any

from fastapi.responses import Response


class AppError(Exception):
    status: int = 500
    title: str = "internal_error"
    code: str = "internal_error"

    def __init__(self, detail: str = "", code: str | None = None, **extra: Any) -> None:
        super().__init__(detail or self.title)
        self.detail = detail or self.title
        if code:
            self.code = code
        self.extra = extra

    def to_response(self, trace_id: str = "") -> Response:
        body = {
            "title": self.title,
            "detail": self.detail,
            "code": self.code,
            "trace_id": trace_id,
            **self.extra,
        }
        return Response(
            status_code=self.status,
            media_type="application/problem+json",
            content=json.dumps(body),
        )


class NotFound(AppError):
    status = 404
    title = "not_found"
    code = "not_found"


class Conflict(AppError):
    status = 409
    title = "conflict"
    code = "conflict"


class AlreadyExists(Conflict):
    code = "already_exists"


class Unauthorized(AppError):
    status = 401
    title = "unauthorized"
    code = "unauthorized"


class Forbidden(AppError):
    status = 403
    title = "forbidden"
    code = "forbidden"


class BadRequest(AppError):
    status = 400
    title = "bad_request"
    code = "bad_request"


class RateLimited(AppError):
    status = 429
    title = "rate_limited"
    code = "rate_limited"
