"""Baseline: core tables + partitioned slots/consultations/audit + outbox + idempotency.

Revision ID: 0001
"""

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

from alembic import op  # noqa: E402


def upgrade() -> None:
    # NOTE: one statement per op.execute — asyncpg cannot prepare multi-command strings.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext;")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

    op.execute(
        """CREATE TABLE users (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          email CITEXT UNIQUE NOT NULL,
          password_hash TEXT NOT NULL,
          role TEXT NOT NULL CHECK (role IN ('patient','doctor','admin')),
          mfa_secret TEXT,
          is_active BOOLEAN NOT NULL DEFAULT TRUE,
          deleted_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );"""
    )
    op.execute(
        """CREATE TABLE profiles (
          user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
          full_name TEXT NOT NULL,
          phone TEXT
        );"""
    )
    op.execute(
        """CREATE TABLE doctors (
          user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
          specialization TEXT NOT NULL,
          license_no TEXT UNIQUE NOT NULL,
          bio TEXT
        );"""
    )
    op.execute(
        "CREATE INDEX doctors_specialization_trgm "
        "ON doctors USING gin (specialization gin_trgm_ops);"
    )

    # availability_slots HASH(doctor_id) -> 8 partitions. PK must include partition key.
    op.execute(
        """CREATE TABLE availability_slots (
          id UUID NOT NULL DEFAULT gen_random_uuid(),
          doctor_id UUID NOT NULL REFERENCES doctors(user_id),
          starts_at TIMESTAMPTZ NOT NULL,
          ends_at TIMESTAMPTZ NOT NULL,
          status TEXT NOT NULL DEFAULT 'open'
            CHECK (status IN ('open','held','booked','cancelled')),
          version INT NOT NULL DEFAULT 1,
          PRIMARY KEY (id, doctor_id)
        ) PARTITION BY HASH (doctor_id);"""
    )
    for i in range(8):
        op.execute(
            f"CREATE TABLE availability_slots_p{i} "
            f"PARTITION OF availability_slots FOR VALUES WITH (MODULUS 8, REMAINDER {i});"
        )
    op.execute(
        "CREATE INDEX slots_doctor_status "
        "ON availability_slots (doctor_id, status, starts_at);"
    )

    # consultations RANGE(created_at) -> monthly. PK includes partition key.
    op.execute(
        """CREATE TABLE consultations (
          id UUID NOT NULL DEFAULT gen_random_uuid(),
          patient_id UUID NOT NULL REFERENCES users(id),
          doctor_id UUID NOT NULL,
          slot_id UUID NOT NULL,
          status TEXT NOT NULL DEFAULT 'held'
            CHECK (status IN ('held','confirmed','in_progress','completed','cancelled')),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          PRIMARY KEY (id, created_at)
        ) PARTITION BY RANGE (created_at);"""
    )
    op.execute(
        "CREATE TABLE consultations_2026_09 PARTITION OF consultations "
        "FOR VALUES FROM ('2026-09-01') TO ('2026-10-01');"
    )
    op.execute(
        "CREATE TABLE consultations_2026_10 PARTITION OF consultations "
        "FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');"
    )
    op.execute(
        "CREATE INDEX consultations_patient_created "
        "ON consultations (patient_id, created_at DESC);"
    )

    op.execute(
        """CREATE TABLE prescriptions (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          consultation_id UUID NOT NULL,
          encrypted_payload BYTEA NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          deleted_at TIMESTAMPTZ
        );"""
    )
    op.execute(
        """CREATE TABLE payments (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          consultation_id UUID NOT NULL UNIQUE,
          amount INT NOT NULL,
          currency TEXT NOT NULL DEFAULT 'INR',
          status TEXT NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending','paid','failed','refunded')),
          gateway_ref TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );"""
    )
    op.execute(
        """CREATE TABLE outbox_events (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          aggregate TEXT NOT NULL,
          event TEXT NOT NULL,
          payload JSONB NOT NULL,
          processed BOOLEAN NOT NULL DEFAULT FALSE,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          processed_at TIMESTAMPTZ
        );"""
    )
    op.execute(
        "CREATE INDEX outbox_unprocessed ON outbox_events (created_at) "
        "WHERE processed = FALSE;"
    )
    op.execute(
        """CREATE TABLE idempotency_keys (
          key TEXT PRIMARY KEY,
          status TEXT NOT NULL DEFAULT 'pending',
          response_code INT,
          response_body JSONB,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );"""
    )

    # audit_logs RANGE(ts) weekly + chain hash columns.
    op.execute(
        """CREATE TABLE audit_logs (
          id UUID NOT NULL DEFAULT gen_random_uuid(),
          ts TIMESTAMPTZ NOT NULL DEFAULT now(),
          actor TEXT NOT NULL,
          action TEXT NOT NULL,
          entity TEXT NOT NULL,
          entity_id TEXT NOT NULL,
          payload JSONB NOT NULL DEFAULT '{}',
          prev_hash TEXT NOT NULL DEFAULT '',
          hash TEXT NOT NULL DEFAULT '',
          PRIMARY KEY (id, ts)
        ) PARTITION BY RANGE (ts);"""
    )
    op.execute(
        "CREATE TABLE audit_logs_2026_w38 PARTITION OF audit_logs "
        "FOR VALUES FROM ('2026-09-14') TO ('2026-09-21');"
    )
    op.execute(
        "CREATE TABLE audit_logs_2026_w39 PARTITION OF audit_logs "
        "FOR VALUES FROM ('2026-09-21') TO ('2026-09-28');"
    )
    op.execute("CREATE INDEX audit_entity_idx ON audit_logs (entity, entity_id);")


def downgrade() -> None:
    for t in [
        "audit_logs_2026_w39",
        "audit_logs_2026_w38",
        "audit_logs",
        "idempotency_keys",
        "outbox_events",
        "payments",
        "prescriptions",
        "consultations_2026_10",
        "consultations_2026_09",
        "consultations",
        "availability_slots_p7",
        "availability_slots_p6",
        "availability_slots_p5",
        "availability_slots_p4",
        "availability_slots_p3",
        "availability_slots_p2",
        "availability_slots_p1",
        "availability_slots_p0",
        "availability_slots",
        "doctors",
        "profiles",
        "users",
    ]:
        op.execute(f"DROP TABLE IF EXISTS {t};")
