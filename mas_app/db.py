from __future__ import annotations

import time
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import create_engine, event, func, inspect, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings
from .models import Base, FileCleanupQueue, Room, RoomState, SchemaInfo, Speaker, SpeakerTimerState, SpeechFile, User

SCHEMA_VERSION = 4


def make_engine(settings: Settings):
    connect_args = {}
    if settings.database_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False, "timeout": 30}
    return create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True, future=True)


def configure_sqlite(engine) -> None:
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


def _add_column_if_missing(engine, table: str, column: str, ddl: str) -> None:
    inspector = inspect(engine)
    if table not in inspector.get_table_names():
        return
    names = {c["name"] for c in inspector.get_columns(table)}
    if column in names:
        return
    with engine.begin() as conn:
        conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {ddl}'))


def _table_has_column(engine, table: str, column: str) -> bool:
    inspector = inspect(engine)
    return table in inspector.get_table_names() and column in {c["name"] for c in inspector.get_columns(table)}


def _repair_speaker_order(engine) -> None:
    with Session(engine) as db:
        rooms = db.scalars(select(Room)).all()
        for room in rooms:
            speakers = list(db.scalars(select(Speaker).where(Speaker.room_id == room.id).order_by(Speaker.order_index, Speaker.id)).all())
            for i, speaker in enumerate(speakers):
                speaker.order_index = -(i + 1)
            db.flush()
            for i, speaker in enumerate(speakers):
                speaker.order_index = i
        db.commit()


def _dedupe_timer_states(engine) -> None:
    with Session(engine) as db:
        rows = db.scalars(select(SpeakerTimerState).order_by(SpeakerTimerState.id)).all()
        groups: dict[tuple[int, int], list[SpeakerTimerState]] = {}
        for row in rows:
            groups.setdefault((row.room_id, row.speaker_id), []).append(row)
        changed = False
        for _key, group in groups.items():
            if len(group) <= 1:
                continue
            keep = group[0]
            keep.elapsed_ms = max([keep.elapsed_ms or 0] + [x.elapsed_ms or 0 for x in group[1:]])
            keep.overtime_ms = max([keep.overtime_ms or 0] + [x.overtime_ms or 0 for x in group[1:]])
            keep.elapsed_seconds = keep.elapsed_ms // 1000
            keep.overtime_seconds = keep.overtime_ms // 1000
            for extra in group[1:]:
                db.delete(extra)
            changed = True
        if changed:
            db.commit()



def _dedupe_room_states(engine) -> None:
    with Session(engine) as db:
        rows = db.scalars(select(RoomState).order_by(RoomState.id)).all()
        groups: dict[int, list[RoomState]] = {}
        for row in rows:
            groups.setdefault(row.room_id, []).append(row)
        changed = False
        for _room_id, group in groups.items():
            if len(group) <= 1:
                continue
            keep = group[0]
            # Keep the most advanced timer state found in legacy duplicates.
            keep.elapsed_ms = max([keep.elapsed_ms or 0] + [x.elapsed_ms or 0 for x in group[1:]])
            keep.overtime_ms = max([keep.overtime_ms or 0] + [x.overtime_ms or 0 for x in group[1:]])
            if keep.current_speaker_id is None:
                keep.current_speaker_id = next((x.current_speaker_id for x in group[1:] if x.current_speaker_id is not None), None)
            keep.running = any(bool(x.running) for x in group)
            keep.started_at_ms = max([keep.started_at_ms or 0] + [x.started_at_ms or 0 for x in group[1:]]) or None
            keep.elapsed_seconds = keep.elapsed_ms // 1000
            keep.overtime_seconds = keep.overtime_ms // 1000
            for extra in group[1:]:
                db.delete(extra)
            changed = True
        if changed:
            db.commit()


def _dedupe_storage_records(engine) -> None:
    """Repair duplicate physical-storage references before creating unique indexes."""
    with Session(engine) as db:
        changed = False
        rows = db.scalars(select(SpeechFile).order_by(SpeechFile.id)).all()
        groups: dict[str, list[SpeechFile]] = {}
        for row in rows:
            groups.setdefault(row.storage_name, []).append(row)
        for _storage_name, group in groups.items():
            if len(group) <= 1:
                continue
            # Keep the oldest metadata row; storage accounting is recomputed afterwards.
            for extra in group[1:]:
                db.delete(extra)
            changed = True

        cleanup_rows = db.scalars(select(FileCleanupQueue).order_by(FileCleanupQueue.id)).all()
        cleanup_groups: dict[str, list[FileCleanupQueue]] = {}
        for row in cleanup_rows:
            cleanup_groups.setdefault(row.storage_name, []).append(row)
        for _storage_name, group in cleanup_groups.items():
            if len(group) <= 1:
                continue
            keep = group[0]
            keep.attempts = max([int(keep.attempts or 0)] + [int(x.attempts or 0) for x in group[1:]])
            keep.next_attempt_at = min([int(keep.next_attempt_at or 0)] + [int(x.next_attempt_at or 0) for x in group[1:]])
            for extra in group[1:]:
                db.delete(extra)
            changed = True
        if changed:
            db.commit()

def _backfill_timer_precision(engine) -> None:
    with Session(engine) as db:
        timers = db.scalars(select(SpeakerTimerState)).all()
        for timer in timers:
            if not timer.elapsed_ms and timer.elapsed_seconds:
                timer.elapsed_ms = max(0, int(timer.elapsed_seconds)) * 1000
            if not timer.overtime_ms and timer.overtime_seconds:
                timer.overtime_ms = max(0, int(timer.overtime_seconds)) * 1000
            timer.elapsed_seconds = max(0, int(timer.elapsed_ms or 0) // 1000)
            timer.overtime_seconds = max(0, int(timer.overtime_ms or 0) // 1000)
        states = db.scalars(select(RoomState)).all()
        for state in states:
            if not state.elapsed_ms and state.elapsed_seconds:
                state.elapsed_ms = max(0, int(state.elapsed_seconds)) * 1000
            if not state.overtime_ms and state.overtime_seconds:
                state.overtime_ms = max(0, int(state.overtime_seconds)) * 1000
            if state.started_at_ms is None and state.started_at is not None:
                value = state.started_at
                try:
                    if isinstance(value, datetime):
                        state.started_at_ms = int(value.timestamp() * 1000)
                    elif isinstance(value, str):
                        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                        state.started_at_ms = int(parsed.timestamp() * 1000)
                    else:
                        numeric = float(value)
                        state.started_at_ms = int(numeric * (1000 if numeric < 10_000_000_000 else 1))
                except (TypeError, ValueError, OverflowError):
                    state.started_at_ms = None
            state.elapsed_seconds = max(0, int(state.elapsed_ms or 0) // 1000)
            state.overtime_seconds = max(0, int(state.overtime_ms or 0) // 1000)
        db.commit()


def _backfill_room_storage_and_profile_flags(engine) -> None:
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


def _migrate_legacy_room_state(engine) -> None:
    inspector = inspect(engine)
    if "room_states" not in inspector.get_table_names() or "speakers" not in inspector.get_table_names():
        return
    with Session(engine) as db:
        states = db.scalars(select(RoomState)).all()
        for state in states:
            if state.current_speaker_id is None:
                speakers = db.scalars(
                    select(Speaker).where(Speaker.room_id == state.room_id, Speaker.name != "").order_by(Speaker.order_index, Speaker.id)
                ).all()
                if speakers and 0 <= (state.current_index or 0) < len(speakers):
                    state.current_speaker_id = speakers[state.current_index].id
            state.version = max(1, state.version or 1)
            state.updated_at = int(state.updated_at or time.time())
        db.commit()


def _ensure_room_states(engine) -> None:
    with Session(engine) as db:
        rooms = db.scalars(select(Room)).all()
        for room in rooms:
            exists = db.scalar(select(RoomState.id).where(RoomState.room_id == room.id))
            if exists is None:
                db.add(RoomState(room_id=room.id, updated_at=int(time.time()), version=1))
        db.commit()


def _create_missing_indexes(engine) -> None:
    # Legacy tables may predate indexes declared by the current ORM. These are required for data integrity.
    statements = [
        'CREATE INDEX IF NOT EXISTS ix_speakers_room_order ON speakers (room_id, order_index)',
        'CREATE INDEX IF NOT EXISTS ix_timer_room_speaker ON speaker_timer_states (room_id, speaker_id)',
        'CREATE INDEX IF NOT EXISTS ix_room_owner ON rooms (owner_id)',
        'CREATE INDEX IF NOT EXISTS ix_files_room ON speech_files (room_id)',
        'CREATE INDEX IF NOT EXISTS ix_sessions_expiry ON auth_sessions (expires_at)',
    ]
    for statement in statements:
        with engine.begin() as conn:
            conn.execute(text(statement))
    for statement in [
        'CREATE UNIQUE INDEX IF NOT EXISTS uq_users_username_legacy ON users (username)',
        'CREATE UNIQUE INDEX IF NOT EXISTS uq_auth_session_token_legacy ON auth_sessions (token_hash)',
        'CREATE UNIQUE INDEX IF NOT EXISTS uq_speaker_room_order_legacy ON speakers (room_id, order_index)',
        'CREATE UNIQUE INDEX IF NOT EXISTS uq_timer_room_speaker_legacy ON speaker_timer_states (room_id, speaker_id)',
        'CREATE UNIQUE INDEX IF NOT EXISTS uq_cleanup_storage_name_legacy ON file_cleanup_queue (storage_name)',
        'CREATE UNIQUE INDEX IF NOT EXISTS uq_room_state_room_legacy ON room_states (room_id)',
        'CREATE UNIQUE INDEX IF NOT EXISTS uq_speech_file_storage_name_legacy ON speech_files (storage_name)',
    ]:
        with engine.begin() as conn:
            conn.execute(text(statement))


def initialize_database(engine) -> None:
    Base.metadata.create_all(engine)

    # Preserve old data while adding all columns introduced by the rewrite.
    column_specs = {
        ("room_states", "current_speaker_id"): "INTEGER NULL",
        ("room_states", "version"): "INTEGER NOT NULL DEFAULT 1",
        ("room_states", "current_index"): "INTEGER NOT NULL DEFAULT 0",
        ("room_states", "elapsed_seconds"): "INTEGER NOT NULL DEFAULT 0",
        ("room_states", "overtime_seconds"): "INTEGER NOT NULL DEFAULT 0",
        ("room_states", "running"): "BOOLEAN NOT NULL DEFAULT FALSE",
        ("room_states", "started_at"): "INTEGER NULL",
        ("room_states", "started_at_ms"): "BIGINT NULL",
        ("room_states", "elapsed_ms"): "BIGINT NOT NULL DEFAULT 0",
        ("room_states", "overtime_ms"): "BIGINT NOT NULL DEFAULT 0",
        ("room_states", "updated_at"): "INTEGER NOT NULL DEFAULT 0",
        ("speakers", "is_finished"): "BOOLEAN NOT NULL DEFAULT FALSE",
        ("speakers", "finished_at_ms"): "BIGINT NULL",
        ("speaker_timer_states", "elapsed_ms"): "BIGINT NOT NULL DEFAULT 0",
        ("speaker_timer_states", "overtime_ms"): "BIGINT NOT NULL DEFAULT 0",
        ("speaker_timer_states", "updated_at"): "INTEGER NOT NULL DEFAULT 0",
        ("rooms", "storage_used_bytes"): "BIGINT NOT NULL DEFAULT 0",
        ("rooms", "version"): "INTEGER NOT NULL DEFAULT 1",
        ("users", "profile_completed"): "BOOLEAN NOT NULL DEFAULT FALSE",
        ("file_cleanup_queue", "created_at"): "INTEGER NOT NULL DEFAULT 0",
        ("file_cleanup_queue", "next_attempt_at"): "INTEGER NOT NULL DEFAULT 0",
    }
    for (table, column), ddl in column_specs.items():
        _add_column_if_missing(engine, table, column, ddl)

    _repair_speaker_order(engine)
    _dedupe_timer_states(engine)
    _dedupe_room_states(engine)
    _backfill_timer_precision(engine)
    _migrate_legacy_room_state(engine)
    _ensure_room_states(engine)
    _dedupe_storage_records(engine)
    _backfill_room_storage_and_profile_flags(engine)
    _create_missing_indexes(engine)

    with Session(engine) as db:
        info = db.scalar(select(SchemaInfo).where(SchemaInfo.id == 1))
        if info is None:
            db.add(SchemaInfo(id=1, version=SCHEMA_VERSION))
        else:
            info.version = max(int(info.version or 1), SCHEMA_VERSION)
        db.commit()


def session_factory(engine):
    return sessionmaker(bind=engine, autoflush=True, expire_on_commit=False, future=True)
