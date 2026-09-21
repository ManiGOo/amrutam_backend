from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "amrutam"
    app_env: str = "local"
    api_v1_prefix: str = "/v1"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://amrutam:amrutam@localhost:5432/amrutam"
    replica_database_url: str = "postgresql+asyncpg://amrutam:amrutam@localhost:5433/amrutam"
    redis_url: str = "redis://localhost:6379/0"

    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"  # noqa: S105 — local dev default only
    s3_secret_key: str = "minioadmin"  # noqa: S105 — local dev default only
    s3_bucket: str = "rx-pdfs"

    jwt_private_key_path: str = "/run/secrets/jwt_private.pem"
    jwt_public_key_path: str = "/run/secrets/jwt_public.pem"
    jwt_kid: str = "local-1"
    jwt_access_ttl_min: int = 15
    jwt_refresh_ttl_days: int = 7

    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    otel_enabled: bool = False  # set OTEL_ENABLED=true in compose/prod only

    # Day 3: prescriptions KEK (base64 32B; dev default is NOT for prod),
    # payments mock-webhook shared secret.
    prescription_kek_b64: str = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="  # noqa: S105
    payment_webhook_secret: str = "local-webhook-secret"  # noqa: S105


@lru_cache
def get_settings() -> Settings:
    return Settings()
