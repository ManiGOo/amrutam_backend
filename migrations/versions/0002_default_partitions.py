"""Add DEFAULT partitions so writes never fail outside pre-created monthly/weekly ranges.

Revision ID: 0002
"""

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

from alembic import op  # noqa: E402


def upgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS consultations_default "
        "PARTITION OF consultations DEFAULT;"
    )
    op.execute(
        "CREATE TABLE IF NOT EXISTS audit_logs_default PARTITION OF audit_logs DEFAULT;"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS consultations_default;")
    op.execute("DROP TABLE IF EXISTS audit_logs_default;")
