"""Prometheus business metrics + best-effort OTel tracing.

- /metrics via prometheus-fastapi-instrumentator (RED per route).
- Business counters incremented in services (bookings, payments, idempotency replays).
- OTel: FastAPI/AsyncPG/Redis instrumented with OTLP export; any failure is
  swallowed so the API never depends on the collector (tests run without it).
"""

from __future__ import annotations

from fastapi import FastAPI
from prometheus_client import Counter
from prometheus_fastapi_instrumentator import Instrumentator

from amrutam.core.logging import get_logger

log = get_logger("otel")

_traced = False

bookings_total = Counter("bookings_total", "Bookings created", ["status"])
payments_total = Counter("payments_total", "Payments settled", ["status"])
idempotency_replays_total = Counter(
    "idempotency_replays_total", "Idempotent replays served from cache"
)
outbox_relayed_total = Counter("outbox_relayed_total", "Outbox events relayed to stream", ["event"])


def setup_metrics(app: FastAPI) -> None:
    Instrumentator().instrument(app).expose(app, endpoint="/metrics")


def setup_tracing(app: FastAPI, otlp_endpoint: str, enabled: bool = False) -> None:
    global _traced
    if not enabled or _traced:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.redis import RedisInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": "amrutam-api"})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True))
        )
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app)
        AsyncPGInstrumentor().instrument()  # type: ignore[no-untyped-call]
        RedisInstrumentor().instrument()
        _traced = True
        log.info("tracing_enabled", endpoint=otlp_endpoint)
    except Exception as e:  # noqa: BLE001
        log.info("tracing_disabled", reason=str(e))
