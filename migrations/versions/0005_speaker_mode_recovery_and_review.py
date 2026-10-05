"""Add speaker access, one-time recovery and file review without rewriting data.

All new columns have either a safe default or remain nullable. Existing users,
rooms, speakers, files, timers and recording chunks are retained unchanged.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0005_speaker_mode_recovery_and_review"
down_revision = "0004_legacy_auth_schema_compat"
branch_labels = None
depends_on = None

ACTIVE_RECORDING_PREDICATE = "status IN ('recording', 'paused', 'finalizing')"


def _existing_columns(table: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def _existing_indexes(table: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return set()
    return {index["name"] for index in inspector.get_indexes(table)}


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    if column.name not in _existing_columns(table):
        op.add_column(table, column)


def _replace_recording_index() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect != "postgresql":
        indexes = _existing_indexes("recording_sessions")
        if "uq_recording_sessions_one_active_per_room" in indexes:
            op.drop_index("uq_recording_sessions_one_active_per_room", table_name="recording_sessions")
        if "uq_recording_sessions_one_active_per_room_speaker" not in _existing_indexes("recording_sessions"):
            op.create_index(
                "uq_recording_sessions_one_active_per_room_speaker",
                "recording_sessions",
                ["room_id", "speaker_id"],
                unique=True,
                sqlite_where=sa.text(ACTIVE_RECORDING_PREDICATE),
            )
        return

    duplicate = bind.execute(
        sa.text(
            "SELECT 1 FROM recording_sessions "
            "WHERE speaker_id IS NOT NULL AND status IN ('recording','paused','finalizing') "
            "GROUP BY room_id, speaker_id HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).scalar_one_or_none()

    # PostgreSQL CREATE/DROP INDEX CONCURRENTLY must run outside a transaction.
    # This reduces interference with the still-live previous Render instance.
    with op.get_context().autocommit_block():
        bind.execute(sa.text("DROP INDEX CONCURRENTLY IF EXISTS uq_recording_sessions_one_active_per_room"))
        if duplicate is not None:
            # Preserve every row. A unique index cannot represent existing duplicate
            # active sessions, so keep the lookup index non-unique until those stale
            # rows are explicitly reconciled. The application already serializes room writes.
            bind.execute(
                sa.text(
                    "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                    "ix_recording_sessions_active_room_speaker "
                    "ON recording_sessions (room_id, speaker_id) "
                    "WHERE status IN ('recording','paused','finalizing')"
                )
            )
        else:
            bind.execute(
                sa.text(
                    "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "
                    "uq_recording_sessions_one_active_per_room_speaker "
                    "ON recording_sessions (room_id, speaker_id) "
                    "WHERE status IN ('recording','paused','finalizing')"
                )
            )


def _ensure_speaker_code_index() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        if "uq_speaker_room_code_hash" not in _existing_indexes("speakers"):
            op.create_index("uq_speaker_room_code_hash", "speakers", ["room_id", "speaker_code_hash"], unique=True)
        return

    duplicate = bind.execute(
        sa.text(
            "SELECT 1 FROM speakers "
            "WHERE speaker_code_hash IS NOT NULL "
            "GROUP BY room_id, speaker_code_hash HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).scalar_one_or_none()

    with op.get_context().autocommit_block():
        if duplicate is None:
            bind.execute(
                sa.text(
                    "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_speaker_room_code_hash "
                    "ON speakers (room_id, speaker_code_hash)"
                )
            )
        else:
            bind.execute(
                sa.text(
                    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_speaker_room_code_hash "
                    "ON speakers (room_id, speaker_code_hash)"
                )
            )


def upgrade() -> None:
    _add_column_if_missing("users", sa.Column("recovery_code_hash", sa.String(length=64), nullable=True))
    _add_column_if_missing("rooms", sa.Column("speaker_mode_enabled", sa.Boolean(), server_default=sa.false(), nullable=False))
    _add_column_if_missing("rooms", sa.Column("speaker_uploads_enabled", sa.Boolean(), server_default=sa.false(), nullable=False))
    _add_column_if_missing("speakers", sa.Column("speaker_code_hash", sa.String(length=64), nullable=True))
    _add_column_if_missing("speakers", sa.Column("speaker_code_encrypted", sa.String(length=512), nullable=True))
    _add_column_if_missing("speakers", sa.Column("speaker_session_hash", sa.String(length=64), nullable=True))
    _add_column_if_missing("speakers", sa.Column("presence_status", sa.String(length=16), server_default="offline", nullable=False))
    _add_column_if_missing("speakers", sa.Column("presence_last_seen_at_ms", sa.BigInteger(), server_default="0", nullable=False))
    _add_column_if_missing("speech_files", sa.Column("approval_status", sa.String(length=16), server_default="approved", nullable=False))
    _replace_recording_index()
    _ensure_speaker_code_index()


def downgrade() -> None:
    bind = op.get_bind()
    duplicate_active = bind.execute(
        sa.text(
            "SELECT room_id FROM recording_sessions "
            "WHERE status IN ('recording', 'paused', 'finalizing') "
            "GROUP BY room_id HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).scalar_one_or_none()
    if duplicate_active is not None:
        raise RuntimeError(
            "Cannot downgrade while a room has multiple active/paused speaker recordings; "
            "finish or discard those sessions first. No data was changed."
        )

    op.drop_index(
        "uq_recording_sessions_one_active_per_room_speaker",
        table_name="recording_sessions",
    )
    op.create_index(
        "uq_recording_sessions_one_active_per_room",
        "recording_sessions",
        ["room_id"],
        unique=True,
        sqlite_where=sa.text(ACTIVE_RECORDING_PREDICATE),
        postgresql_where=sa.text(ACTIVE_RECORDING_PREDICATE),
    )

    op.drop_column("speech_files", "approval_status")
    op.drop_index("uq_speaker_room_code_hash", table_name="speakers")
    op.drop_column("speakers", "presence_last_seen_at_ms")
    op.drop_column("speakers", "presence_status")
    op.drop_column("speakers", "speaker_session_hash")
    op.drop_column("speakers", "speaker_code_encrypted")
    op.drop_column("speakers", "speaker_code_hash")
    op.drop_column("rooms", "speaker_uploads_enabled")
    op.drop_column("rooms", "speaker_mode_enabled")
    op.drop_column("users", "recovery_code_hash")
