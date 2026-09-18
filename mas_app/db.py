from __future__ import annotations

from contextlib import contextmanager
import time

from sqlalchemy import create_engine, event, func, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings
from .models import Base, Room, RoomState, Speaker, SpeakerTimerState, SpeechFile, User


def make_engine(settings: Settings):
    connect_args = {}
    if settings.database_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False, "timeout": 30}
    return create_engine(
        settings.database_url,
        connect_args=connect_args,
        pool_pre_ping=True,
        future=True,
    )


def configure_sqlite(engine):
    if not engine.url.drivername.startswith("sqlite"):
        return

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


def _add_column_if_missing(engine, table: str, column: str, ddl: str):
    inspector = inspect(engine)
    if table not in inspector.get_table_names():
        return
    names = {c["name"] for c in inspector.get_columns(table)}
    if column in names:
        return
    with engine.begin() as conn:
        conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {ddl}'))


def _backfill_room_storage_and_profile_flags(engine):
    with Session(engine) as db:
        rooms = db.scalars(select(Room)).all()
        for room in rooms:
            total = db.scalar(select(func.coalesce(func.sum(SpeechFile.size_bytes), 0)).where(SpeechFile.room_id == room.id)) or 0
            room.storage_used_bytes = max(0, int(total))
        users = db.scalars(select(User)).all()
        for user in users:
            if not user.profile_completed and (user.account_name or user.age or user.job):
                user.profile_completed = True
        db.commit()


def _migrate_legacy_room_state(engine):
    inspector = inspect(engine)
    if "room_states" not in inspector.get_table_names() or "speakers" not in inspector.get_table_names():
        return

    with Session(engine) as db:
        states = db.scalars(select(RoomState)).all()
        for state in states:
            if state.current_speaker_id is None:
                speakers = db.scalars(
                    select(Speaker)
                    .where(Speaker.room_id == state.room_id, Speaker.name != "")
                    .order_by(Speaker.order_index, Speaker.id)
                ).all()
                if speakers and 0 <= (state.current_index or 0) < len(speakers):
                    state.current_speaker_id = speakers[state.current_index].id

            if state.current_speaker_id is not None and (state.elapsed_seconds or 0) > 0:
                timer = db.scalar(
                    select(SpeakerTimerState).where(
                        SpeakerTimerState.room_id == state.room_id,
                        SpeakerTimerState.speaker_id == state.current_speaker_id,
                    )
                )
                if timer is None:
                    db.add(
                        SpeakerTimerState(
                            room_id=state.room_id,
                            speaker_id=state.current_speaker_id,
                            elapsed_seconds=max(0, state.elapsed_seconds or 0),
                            overtime_seconds=max(0, state.overtime_seconds or 0),
                            updated_at=int(time.time()),
                        )
                    )
            state.version = max(1, state.version or 1)
            state.updated_at = int(state.updated_at or time.time())
        db.commit()


def initialize_database(engine):
    Base.metadata.create_all(engine)

    # Minimal, idempotent migration for the schema used by the previous MAS release.
    # These statements only add missing fields; existing user/room/file data is preserved.
    _add_column_if_missing(engine, "room_states", "current_speaker_id", "INTEGER NULL")
    _add_column_if_missing(engine, "room_states", "version", "INTEGER NOT NULL DEFAULT 1")
    _add_column_if_missing(engine, "room_states", "current_index", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(engine, "room_states", "elapsed_seconds", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(engine, "room_states", "overtime_seconds", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(engine, "room_states", "running", "BOOLEAN NOT NULL DEFAULT 0")
    _add_column_if_missing(engine, "room_states", "started_at", "TIMESTAMP NULL")
    _add_column_if_missing(engine, "room_states", "updated_at", "INTEGER NULL")

    _add_column_if_missing(engine, "rooms", "storage_used_bytes", "BIGINT NOT NULL DEFAULT 0")
    _add_column_if_missing(engine, "rooms", "version", "INTEGER NOT NULL DEFAULT 1")
    _add_column_if_missing(engine, "speech_files", "duration_seconds", "INTEGER NULL")
    _add_column_if_missing(engine, "auth_sessions", "last_seen_at", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(engine, "speaker_timer_states", "updated_at", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(engine, "speaker_timer_states", "version", "INTEGER NOT NULL DEFAULT 1")
    _add_column_if_missing(engine, "users", "profile_completed", "BOOLEAN NOT NULL DEFAULT 0")
    _add_column_if_missing(engine, "speakers", "description", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(engine, "speakers", "speaking_seconds", "INTEGER NOT NULL DEFAULT 300")

    _backfill_room_storage_and_profile_flags(engine)
    _migrate_legacy_room_state(engine)


def session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


@contextmanager
def transaction(session_factory_obj):
    with session_factory_obj.begin() as db:
        yield db
