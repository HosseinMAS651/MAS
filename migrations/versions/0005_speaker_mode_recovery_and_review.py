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


def upgrade() -> None:
    op.add_column("users", sa.Column("recovery_code_hash", sa.String(length=64), nullable=True))

    op.add_column(
        "rooms",
        sa.Column("speaker_mode_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "rooms",
        sa.Column("speaker_uploads_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
    )

    op.add_column("speakers", sa.Column("speaker_code_hash", sa.String(length=64), nullable=True))
    op.add_column("speakers", sa.Column("speaker_code_encrypted", sa.String(length=512), nullable=True))
    op.add_column("speakers", sa.Column("speaker_session_hash", sa.String(length=64), nullable=True))
    op.add_column(
        "speakers",
        sa.Column("presence_status", sa.String(length=16), server_default="offline", nullable=False),
    )
    op.add_column(
        "speakers",
        sa.Column("presence_last_seen_at_ms", sa.BigInteger(), server_default="0", nullable=False),
    )
    op.create_index(
        "uq_speaker_room_code_hash",
        "speakers",
        ["room_id", "speaker_code_hash"],
        unique=True,
    )

    op.add_column(
        "speech_files",
        sa.Column("approval_status", sa.String(length=16), server_default="approved", nullable=False),
    )

    # A paused recording for speaker A must not prevent recording speaker B.
    # Existing installations could contain at most one active row per room, so
    # replacing this index does not change any recording row or object in storage.
    op.drop_index("uq_recording_sessions_one_active_per_room", table_name="recording_sessions")
    op.create_index(
        "uq_recording_sessions_one_active_per_room_speaker",
        "recording_sessions",
        ["room_id", "speaker_id"],
        unique=True,
        sqlite_where=sa.text(ACTIVE_RECORDING_PREDICATE),
        postgresql_where=sa.text(ACTIVE_RECORDING_PREDICATE),
    )


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
