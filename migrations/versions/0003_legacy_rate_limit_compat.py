"""Make removed legacy rate-limit columns nullable on PostgreSQL."""
from __future__ import annotations

from alembic import op
from sqlalchemy import inspect

revision = "0003_legacy_rate_limit_compat"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    inspector = inspect(bind)
    if "rate_limit_buckets" not in inspector.get_table_names():
        return

    columns = {c["name"]: c for c in inspector.get_columns("rate_limit_buckets")}
    for name in ("window_started_at", "blocked_until"):
        column = columns.get(name)
        if column and not column.get("nullable", True):
            op.alter_column("rate_limit_buckets", name, nullable=True)


def downgrade() -> None:
    # Do not re-introduce a NOT NULL requirement that the current ORM does not
    # populate. This downgrade is intentionally a no-op for data safety.
    pass
