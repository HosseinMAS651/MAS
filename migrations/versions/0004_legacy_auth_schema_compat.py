"""Relax legacy NOT NULL columns no longer written by the v2 ORM.

Some Render/PostgreSQL databases can retain columns from the pre-v2 schema
even after a data reset. Those columns must not block inserts that only use
the current millisecond/hash columns.
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import inspect

revision = "0004_legacy_auth_schema_compat"
down_revision = "0003_legacy_rate_limit_compat"
branch_labels = None
depends_on = None


LEGACY_COLUMNS = {
    "users": ("created_at", "updated_at"),
    "auth_sessions": ("csrf_token",),
    "rate_limit_buckets": ("window_started_at", "blocked_until"),
    "rooms": ("created_at",),
}


def _drop_not_null_if_present(table: str, columns: tuple[str, ...]) -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if table not in inspector.get_table_names():
        return

    current = {c["name"]: c for c in inspector.get_columns(table)}
    for name in columns:
        column = current.get(name)
        if not column or column.get("nullable", True):
            continue

        if bind.dialect.name == "postgresql":
            op.execute(
                f'ALTER TABLE "{table}" ALTER COLUMN "{name}" DROP NOT NULL'
            )
        else:
            with op.batch_alter_table(table, schema=None) as batch_op:
                batch_op.alter_column(name, nullable=True)


def upgrade() -> None:
    for table, columns in LEGACY_COLUMNS.items():
        _drop_not_null_if_present(table, columns)


def downgrade() -> None:
    # Intentionally a no-op: making legacy columns nullable is data-preserving
    # and restoring NOT NULL could make the current ORM fail again.
    pass
