from __future__ import annotations

import secrets
import time
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker
from .config import Settings
from .models import Base, FileCleanupQueue, Room, RoomState, SchemaInfo, SpeechFile, Speaker, SpeakerTimerState, User

DB_SCHEMA_VERSION = 4


def make_engine(settings: Settings):
    connect_args = {"check_same_thread": False, "timeout": 30} if settings.database_url.startswith("sqlite") else {}
    return create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True, future=True)


def configure_sqlite(engine):
    if not engine.url.drivername.startswith("sqlite"):
        return
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(conn, _record):
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()


def _add_column_if_missing(engine, table: str, column: str, ddl: str):
    inspector = inspect(engine)
    if table not in inspector.get_table_names():
        return
    names = {c["name"] for c in inspector.get_columns(table)}
    if column not in names:
        with engine.begin() as conn:
            conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {ddl}'))


def _ensure_index(engine, ddl: str):
    with engine.begin() as conn:
        conn.execute(text(ddl))


def _migrate_started_at_type(engine):
    """Normalize the legacy PostgreSQL TIMESTAMP started_at to Unix seconds.

    The previous release could create this column as TIMESTAMP, while the current
    model stores Unix seconds. Existing values are converted in-place.
    SQLite is intentionally left untouched because it has dynamic type affinity.
    """
    if engine.dialect.name != "postgresql":
        return
    inspector = inspect(engine)
    if "room_states" not in inspector.get_table_names():
        return
    column = next((c for c in inspector.get_columns("room_states") if c["name"] == "started_at"), None)
    if column is None:
        return
    typename = str(column["type"]).lower()
    if "int" in typename or "numeric" in typename or "double" in typename:
        return
    with engine.begin() as conn:
        conn.execute(text('ALTER TABLE "room_states" ALTER COLUMN "started_at" TYPE BIGINT USING CASE WHEN "started_at" IS NULL THEN NULL ELSE EXTRACT(EPOCH FROM "started_at")::BIGINT END'))


def _backfill(engine):
    with Session(engine) as db:
        rooms = db.scalars(select(Room)).all()
        for room in rooms:
            if not room.public_token:
                token = secrets.token_urlsafe(32)
                while db.scalar(select(Room.id).where(Room.public_token == token)):
                    token = secrets.token_urlsafe(32)
                room.public_token = token
        totals = {}
        for room_id, total in db.execute(select(SpeechFile.room_id, text("COALESCE(SUM(size_bytes),0)")).group_by(SpeechFile.room_id)):
            totals[int(room_id)] = int(total or 0)
        for room in rooms:
            room.storage_used_bytes = totals.get(room.id, 0)
        files = db.scalars(select(SpeechFile).where(SpeechFile.upload_type == "recording")).all()
        for f in files:
            if not f.room_name_snapshot:
                room = db.get(Room, f.room_id)
                if room: f.room_name_snapshot = room.name
            if not f.speaker_name_snapshot and f.speaker_id:
                speaker = db.get(Speaker, f.speaker_id)
                if speaker: f.speaker_name_snapshot = speaker.name
        users = db.scalars(select(User)).all()
        for user in users:
            if not user.profile_completed and (user.account_name or user.age or user.job):
                user.profile_completed = True
        state_rows = db.scalars(select(RoomState)).all()
        for state in state_rows:
            state.version = max(1, state.version or 1)
            state.updated_at = int(state.updated_at or time.time())
            if state.current_speaker_id is None:
                speakers = db.scalars(select(Speaker).where(Speaker.room_id == state.room_id, Speaker.name != "").order_by(Speaker.order_index, Speaker.id)).all()
                if speakers and 0 <= state.current_index < len(speakers):
                    state.current_speaker_id = speakers[state.current_index].id
        existing = db.get(SchemaInfo, 1)
        if existing is None:
            db.add(SchemaInfo(id=1, version=DB_SCHEMA_VERSION))
        else:
            existing.version = max(existing.version, DB_SCHEMA_VERSION)
        db.commit()


def initialize_database(engine):
    Base.metadata.create_all(engine)
    # Additive migration so the existing MAS database/data remains usable.
    _add_column_if_missing(engine, "rooms", "public_token", "VARCHAR(64)")
    _add_column_if_missing(engine, "room_states", "overtime_allowed", "BOOLEAN NOT NULL DEFAULT 0")
    _add_column_if_missing(engine, "room_states", "completed", "BOOLEAN NOT NULL DEFAULT 0")
    _add_column_if_missing(engine, "speech_files", "speaker_name_snapshot", "VARCHAR(120) NOT NULL DEFAULT ''")
    _add_column_if_missing(engine, "speech_files", "room_name_snapshot", "VARCHAR(160) NOT NULL DEFAULT ''")
    _add_column_if_missing(engine, "room_states", "current_speaker_id", "INTEGER NULL")
    _add_column_if_missing(engine, "room_states", "version", "INTEGER NOT NULL DEFAULT 1")
    _add_column_if_missing(engine, "room_states", "current_index", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(engine, "room_states", "elapsed_seconds", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(engine, "room_states", "overtime_seconds", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(engine, "room_states", "running", "BOOLEAN NOT NULL DEFAULT 0")
    _add_column_if_missing(engine, "room_states", "started_at", "INTEGER NULL")
    _add_column_if_missing(engine, "room_states", "updated_at", "INTEGER NULL")
    _add_column_if_missing(engine, "rooms", "storage_used_bytes", "BIGINT NOT NULL DEFAULT 0")
    _add_column_if_missing(engine, "rooms", "version", "INTEGER NOT NULL DEFAULT 1")
    _add_column_if_missing(engine, "speech_files", "duration_seconds", "INTEGER NULL")
    _add_column_if_missing(engine, "auth_sessions", "last_seen_at", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(engine, "speaker_timer_states", "updated_at", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(engine, "speaker_timer_states", "version", "INTEGER NOT NULL DEFAULT 1")
    _migrate_started_at_type(engine)
    try:
        _ensure_index(engine, "CREATE UNIQUE INDEX IF NOT EXISTS uq_rooms_public_token ON rooms(public_token)")
    except Exception:
        pass
    _backfill(engine)


def session_factory(engine):
    return sessionmaker(bind=engine, autoflush=True, expire_on_commit=False)
