"""Rx envelope columns + analytics materialized views.

Revision ID: 0003
"""

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

from alembic import op  # noqa: E402


def upgrade() -> None:
    op.execute("ALTER TABLE prescriptions ADD COLUMN IF NOT EXISTS wrapped_dek BYTEA;")
    op.execute("ALTER TABLE prescriptions ADD COLUMN IF NOT EXISTS nonce BYTEA;")
    op.execute(
        """CREATE MATERIALIZED VIEW IF NOT EXISTS analytics_daily AS
        SELECT date_trunc('day', created_at)::date AS day,
               status, count(*)::int AS n
        FROM consultations GROUP BY 1, 2;"""
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS analytics_daily_uidx "
        "ON analytics_daily (day, status);"
    )
    op.execute(
        """CREATE MATERIALIZED VIEW IF NOT EXISTS analytics_funnel AS
        SELECT status, count(*)::int AS n FROM consultations GROUP BY 1;"""
    )
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS analytics_funnel_uidx ON analytics_funnel (status);")


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS analytics_funnel;")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS analytics_daily;")
    op.execute("ALTER TABLE prescriptions DROP COLUMN IF EXISTS nonce;")
    op.execute("ALTER TABLE prescriptions DROP COLUMN IF EXISTS wrapped_dek;")
