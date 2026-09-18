from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from .models import FileCleanupQueue, Room, RoomState, Speaker, SpeakerTimerState, SpeechFile
from .storage import safe_storage_path

TIMING_MODES = {"global", "individual"}
ORDER_MODES = {"age", "alpha", "random", "manual"}
GENDERS = {"", "مرد", "زن"}


@dataclass(frozen=True)
class RoomSnapshot:
    room: Room
    speakers: list[Speaker]


def now() -> int:
    return int(time.time())


def validate_room_name(name: str) -> str:
    value = (name or "").strip()
    if not value:
        raise HTTPException(400, "نام اتاق الزامی است.")
    if len(value) > 160:
        raise HTTPException(400, "نام اتاق حداکثر ۱۶۰ کاراکتر است.")
    return value


def validate_speaker_name(name: str) -> str:
    value = (name or "").strip()
    if len(value) > 120:
        raise HTTPException(400, "نام سخنران حداکثر ۱۲۰ کاراکتر است.")
    return value


def validate_capacity(capacity: int, minimum: int = 1, maximum: int = 100) -> int:
    if not minimum <= capacity <= maximum:
        raise HTTPException(400, f"ظرفیت باید بین {minimum} تا {maximum} باشد.")
    return capacity


def room_speakers(db: Session, room_id: int, *, named_only: bool = False) -> list[Speaker]:
    stmt = select(Speaker).where(Speaker.room_id == room_id).order_by(Speaker.order_index, Speaker.id)
    if named_only:
        stmt = stmt.where(Speaker.name != "")
    return list(db.scalars(stmt).all())


def ensure_room_state(db: Session, room_id: int) -> RoomState:
    state = db.scalar(select(RoomState).where(RoomState.room_id == room_id).with_for_update())
    if state is None:
        state = RoomState(
            room_id=room_id,
            current_index=0,
            elapsed_seconds=0,
            overtime_seconds=0,
            running=False,
            started_at=None,
            updated_at=now(),
            current_speaker_id=None,
            version=1,
        )
        db.add(state)
        db.flush()
    return state


def ensure_current_speaker(db: Session, room: Room, state: RoomState, speakers: list[Speaker]) -> Speaker | None:
    if not speakers:
        state.current_speaker_id = None
        state.current_index = 0
        state.running = False
        state.started_at = None
        return None

    ids = {s.id for s in speakers}
    if state.current_speaker_id in ids:
        current = next(s for s in speakers if s.id == state.current_speaker_id)
    else:
        # Migrate an old index if present; otherwise start with the first named speaker.
        if 0 <= state.current_index < len(speakers):
            current = speakers[state.current_index]
        else:
            current = speakers[0]
        state.current_speaker_id = current.id
        state.running = False
        state.started_at = None

    state.current_index = speakers.index(current)
    return current


def timer_for(db: Session, room_id: int, speaker_id: int) -> SpeakerTimerState:
    timer = db.scalar(
        select(SpeakerTimerState)
        .where(SpeakerTimerState.room_id == room_id, SpeakerTimerState.speaker_id == speaker_id)
        .with_for_update()
    )
    if timer is None:
        timer = SpeakerTimerState(
            room_id=room_id,
            speaker_id=speaker_id,
            elapsed_seconds=0,
            overtime_seconds=0,
            updated_at=now(),
        )
        db.add(timer)
        db.flush()
    return timer


def persist_running_elapsed(state: RoomState, timer: SpeakerTimerState, limit_seconds: int) -> None:
    if not state.running or not state.started_at:
        return
    current = now()
    delta = max(0, current - state.started_at)
    if delta:
        timer.elapsed_seconds += delta
        timer.overtime_seconds = max(0, timer.elapsed_seconds - limit_seconds)
        timer.updated_at = current
    state.elapsed_seconds = timer.elapsed_seconds
    state.overtime_seconds = max(0, timer.elapsed_seconds - limit_seconds)
    state.started_at = current
    state.updated_at = current


def timer_values(state: RoomState, timer: SpeakerTimerState, limit_seconds: int) -> tuple[int, int, int]:
    elapsed = timer.elapsed_seconds
    if state.running and state.started_at:
        elapsed += max(0, now() - state.started_at)
    overtime = max(0, elapsed - limit_seconds)
    remaining = max(0, limit_seconds - elapsed)
    return elapsed, remaining, overtime


def state_snapshot(db: Session, room: Room) -> dict:
    speakers = room_speakers(db, room.id, named_only=True)
    state = db.scalar(select(RoomState).where(RoomState.room_id == room.id))
    if state is None:
        # GET /state is read-only: do not create database rows as a side effect.
        return {
            "running": False, "current_index": 0, "current_speaker_id": None,
            "elapsed_seconds": 0, "remaining_seconds": 0, "overtime_seconds": 0,
            "limit_seconds": 0, "total_speakers": len(speakers), "server_time": now(),
            "version": 0, "current_speaker": None,
        }
    current = ensure_current_speaker(db, room, state, speakers)
    if current is None:
        return {
            "running": False,
            "current_index": 0,
            "current_speaker_id": None,
            "elapsed_seconds": 0,
            "remaining_seconds": 0,
            "overtime_seconds": 0,
            "limit_seconds": 0,
            "total_speakers": 0,
            "server_time": now(),
            "version": state.version,
            "current_speaker": None,
        }
    timer = db.scalar(
        select(SpeakerTimerState).where(
            SpeakerTimerState.room_id == room.id,
            SpeakerTimerState.speaker_id == current.id,
        )
    )
    base_elapsed = timer.elapsed_seconds if timer else 0
    base_overtime = timer.overtime_seconds if timer else 0
    limit = room.global_seconds if room.timing_mode == "global" else (current.speaking_seconds or room.global_seconds)
    elapsed = base_elapsed
    if state.running and state.started_at:
        elapsed += max(0, now() - state.started_at)
    overtime = max(0, elapsed - limit) if timer is not None or state.running else base_overtime
    remaining = max(0, limit - elapsed)
    current_payload = {
        "id": current.id,
        "name": current.name,
        "gender": current.gender,
        "age": current.age,
        "description": current.description,
        "seconds": limit,
    }
    return {
        "running": state.running,
        "current_index": speakers.index(current),
        "current_speaker_id": current.id,
        "elapsed_seconds": elapsed,
        "remaining_seconds": remaining,
        "overtime_seconds": overtime,
        "limit_seconds": limit,
        "total_speakers": len(speakers),
        "server_time": now(),
        "version": state.version,
        "current_speaker": current_payload,
    }


def _apply_timer_action_once(db: Session, room: Room, action: str) -> dict:
    state = ensure_room_state(db, room.id)
    speakers = room_speakers(db, room.id, named_only=True)
    current = ensure_current_speaker(db, room, state, speakers)

    if current is None:
        state.running = False
        state.started_at = None
        state.updated_at = now()
        db.commit()
        return state_snapshot(db, room)

    timer = timer_for(db, room.id, current.id)
    limit = room.global_seconds if room.timing_mode == "global" else (current.speaking_seconds or room.global_seconds)

    if state.running:
        persist_running_elapsed(state, timer, limit)

    if action == "start":
        if not state.running:
            state.running = True
            state.started_at = now()
    elif action == "pause":
        state.running = False
        state.started_at = None
    elif action == "reset":
        timer.elapsed_seconds = 0
        timer.overtime_seconds = 0
        timer.updated_at = now()
        state.elapsed_seconds = 0
        state.overtime_seconds = 0
        state.running = False
        state.started_at = None
    elif action in {"next", "prev"}:
        current_idx = speakers.index(current)
        new_idx = current_idx + (1 if action == "next" else -1)
        if 0 <= new_idx < len(speakers):
            new_speaker = speakers[new_idx]
            state.current_speaker_id = new_speaker.id
            state.current_index = new_idx
            state.running = False
            state.started_at = None
            new_timer = timer_for(db, room.id, new_speaker.id)
            new_limit = room.global_seconds if room.timing_mode == "global" else (new_speaker.speaking_seconds or room.global_seconds)
            new_timer.overtime_seconds = max(0, new_timer.elapsed_seconds - new_limit)
            state.elapsed_seconds = new_timer.elapsed_seconds
            state.overtime_seconds = new_timer.overtime_seconds

    state.updated_at = now()
    db.commit()
    return state_snapshot(db, room)


def apply_timer_action(db: Session, room: Room, action: str) -> dict:
    if action not in {"start", "pause", "reset", "next", "prev"}:
        raise HTTPException(404, "دستور نامعتبر است.")
    for attempt in range(3):
        try:
            return _apply_timer_action_once(db, room, action)
        except (StaleDataError, IntegrityError, OperationalError):
            db.rollback()
            if attempt == 2:
                raise HTTPException(409, "وضعیت اتاق همزمان تغییر کرد. دوباره تلاش کنید.")
            time.sleep(0.05 * (attempt + 1))
    raise HTTPException(409, "وضعیت اتاق همزمان تغییر کرد. دوباره تلاش کنید.")


def ordered_speakers(speakers: list[Speaker], mode: str, manual_ids: list[int] | None = None) -> list[Speaker]:
    mode = mode if mode in ORDER_MODES else "manual"
    items = list(speakers)
    if mode == "age":
        items.sort(key=lambda s: (s.age is None, s.age if s.age is not None else 10**9, s.id))
    elif mode == "alpha":
        items.sort(key=lambda s: (not bool(s.name), (s.name or "").casefold(), s.id))
    elif mode == "random":
        secrets.SystemRandom().shuffle(items)
    elif mode == "manual":
        mapping = {s.id: s for s in items}
        requested = manual_ids or []
        seen: set[int] = set()
        ordered = []
        for sid in requested:
            if sid in mapping and sid not in seen:
                ordered.append(mapping[sid])
                seen.add(sid)
        ordered.extend(s for s in items if s.id not in seen)
        items = ordered
    return items


def reserve_room_storage(db: Session, room_id: int, amount: int, maximum: int) -> None:
    if amount < 0:
        raise ValueError("amount must be non-negative")
    if amount == 0:
        return
    result = db.execute(
        update(Room)
        .where(
            Room.id == room_id,
            Room.storage_used_bytes + amount <= maximum,
        )
        .values(storage_used_bytes=Room.storage_used_bytes + amount)
    )
    if result.rowcount != 1:
        raise HTTPException(400, "سهمیهٔ فضای این اتاق پر می‌شود.")


def release_room_storage(db: Session, room_id: int, amount: int) -> None:
    if amount <= 0:
        return
    db.execute(
        update(Room)
        .where(Room.id == room_id)
        .values(storage_used_bytes=func.max(0, Room.storage_used_bytes - amount))
    )


def collect_room_storage(db: Session, room_id: int) -> list[str]:
    return [x for x in db.scalars(select(SpeechFile.storage_name).where(SpeechFile.room_id == room_id)).all()]


def enqueue_cleanup(db: Session, storage_names: list[str]) -> None:
    for name in storage_names:
        if name:
            db.add(FileCleanupQueue(storage_name=name, attempts=0))


def process_cleanup_queue(db: Session, storage_settings, limit: int = 50) -> int:
    rows = db.scalars(
        select(FileCleanupQueue)
        .where(FileCleanupQueue.next_attempt_at <= now())
        .order_by(FileCleanupQueue.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    processed = 0
    for row in rows:
        try:
            path = safe_storage_path(storage_settings, row.storage_name)
        except ValueError:
            row.attempts += 1
            row.next_attempt_at = int(time.time() + 3600)
            continue
        try:
            path.unlink(missing_ok=True)
            db.delete(row)
            processed += 1
        except OSError:
            row.attempts += 1
            delay = min(3600, 2 ** min(row.attempts, 10))
            row.next_attempt_at = int(time.time() + delay)
    db.commit()
    return processed
