from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import Response

from amrutam.api.middleware.audit import AuditMiddleware
from amrutam.api.routes.health import router as health_router
from amrutam.core.config import Settings, get_settings
from amrutam.core.container import Container
from amrutam.core.errors import AppError
from amrutam.core.logging import configure_logging, get_logger
from amrutam.core.observability import setup_metrics, setup_tracing
from amrutam.modules.analytics.router import router as analytics_router
from amrutam.modules.auth.router import router as auth_router
from amrutam.modules.bookings.router import router as bookings_router
from amrutam.modules.consultations.router import router as consultations_router
from amrutam.modules.doctors.router import router as doctors_router
from amrutam.modules.payments.router import router as payments_router
from amrutam.modules.prescriptions.router import router as prescriptions_router
from amrutam.modules.search.router import router as search_router

log = get_logger()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = Container(settings)
        log.info("startup", app=settings.app_name, env=settings.app_env)
        yield
        await app.state.container.close()
        log.info("shutdown")

    app = FastAPI(title="Amrutam Telemedicine API", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> Response:
        trace_id = request.headers.get("x-request-id", "")
        log.error(
            "app_error",
            path=str(request.url.path),
            method=request.method,
            code=exc.code,
            trace_id=trace_id,
        )
        return exc.to_response(trace_id=trace_id)

    @app.exception_handler(Exception)
    async def fallback_handler(request: Request, exc: Exception) -> Response:
        import json

        trace_id = request.headers.get("x-request-id", "")
        log.error(
            "unhandled_error",
            path=str(request.url.path),
            method=request.method,
            error=str(exc),
            trace_id=trace_id,
        )
        return Response(
            status_code=500,
            media_type="application/problem+json",
            content=json.dumps({"title": "internal_error", "trace_id": trace_id}),
        )

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(doctors_router)
    app.include_router(bookings_router)
    app.include_router(consultations_router)
    app.include_router(prescriptions_router)
    app.include_router(payments_router)
    app.include_router(search_router)
    app.include_router(analytics_router)
    app.add_middleware(AuditMiddleware)
    setup_metrics(app)
    setup_tracing(app, settings.otel_exporter_otlp_endpoint, settings.otel_enabled)
    return app


app = create_app()
