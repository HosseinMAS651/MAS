"""guard against concurrent active recordings in one room"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX uq_recording_sessions_one_active_per_room "
        "ON recording_sessions (room_id) "
        "WHERE status IN ('recording', 'paused', 'finalizing')"
    )


def downgrade() -> None:
    op.drop_index("uq_recording_sessions_one_active_per_room", table_name="recording_sessions")
