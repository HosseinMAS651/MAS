from __future__ import annotations

import secrets
import time
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from .models import FileCleanupQueue, Room, RoomState, Speaker, SpeakerTimerState, SpeechFile

TIMING_MODES = {"global", "individual"}
ORDER_MODES = {"age", "alpha", "random", "manual"}
GENDERS = {"", "مرد", "زن"}


def now() -> int:
    return int(time.time())


def as_epoch(value) -> int:
    """Normalize old TIMESTAMP/string values and new Unix-second integers."""
    if value is None:
        return 0
    if isinstance(value, datetime):
        return int(value.timestamp())
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return 0
    try:
        return int(float(text))
    except ValueError:
        pass
    try:
        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return 0


def validate_room_name(name: str) -> str:
    value = (name or "").strip()
    if not value or len(value) > 160:
        raise HTTPException(400, "نام اتاق نامعتبر است.")
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


def room_speakers(db: Session, room_id: int, named_only: bool = False) -> list[Speaker]:
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
            overtime_allowed=False,
            completed=False,
        )
        db.add(state)
        db.flush()
    return state


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


def choose_current_speaker(state: RoomState, speakers: list[Speaker]) -> Speaker | None:
    if not speakers:
        return None
    by_id = {speaker.id: speaker for speaker in speakers}
    if state.current_speaker_id in by_id:
        return by_id[state.current_speaker_id]
    index = state.current_index if 0 <= state.current_index < len(speakers) else 0
    return speakers[index]


def ensure_current_speaker(db: Session, room: Room, state: RoomState, speakers: list[Speaker]) -> Speaker | None:
    current = choose_current_speaker(state, speakers)
    if current is None:
        state.current_speaker_id = None
        state.current_index = 0
        state.running = False
        state.started_at = None
        state.completed = True
        return None
    state.current_speaker_id = current.id
    state.current_index = speakers.index(current)
    return current


def persist_running_elapsed(state: RoomState, timer: SpeakerTimerState, limit_seconds: int) -> None:
    if not state.running or not state.started_at:
        return
    current = now()
    started = as_epoch(state.started_at)
    delta = max(0, current - started)
    if delta:
        timer.elapsed_seconds += delta
        timer.updated_at = current
    state.elapsed_seconds = timer.elapsed_seconds
    state.overtime_seconds = max(0, timer.elapsed_seconds - limit_seconds) if state.overtime_allowed else 0
    state.started_at = current
    state.updated_at = current


def limit_for(room: Room, speaker: Speaker) -> int:
    return room.global_seconds if room.timing_mode == "global" else (speaker.speaking_seconds or room.global_seconds)


def state_snapshot(db: Session, room: Room, auto_expire: bool = False) -> dict:
    speakers = room_speakers(db, room.id, named_only=True)
    state_stmt = select(RoomState).where(RoomState.room_id == room.id)
    state = db.scalar(state_stmt.with_for_update() if auto_expire else state_stmt)
    if state is None:
        return {
            "running": False,
            "current_index": 0,
            "current_speaker_id": None,
            "elapsed_seconds": 0,
            "remaining_seconds": 0,
            "overtime_seconds": 0,
            "limit_seconds": 0,
            "total_speakers": len(speakers),
            "server_time": now(),
            "version": 0,
            "awaiting_decision": False,
            "completed": not speakers,
            "current_speaker": None,
        }

    current = choose_current_speaker(state, speakers)
    if current is None:
        if auto_expire:
            state.current_speaker_id = None
            state.current_index = 0
            state.running = False
            state.started_at = None
            state.completed = True
            state.updated_at = now()
            db.commit()
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
            "awaiting_decision": False,
            "completed": True,
            "current_speaker": None,
        }

    timer_stmt = select(SpeakerTimerState).where(
        SpeakerTimerState.room_id == room.id,
        SpeakerTimerState.speaker_id == current.id,
    )
    timer = db.scalar(timer_stmt.with_for_update() if auto_expire else timer_stmt)
    limit = limit_for(room, current)
    elapsed = timer.elapsed_seconds if timer else 0
    started = as_epoch(state.started_at)
    if state.running and started:
        elapsed += max(0, now() - started)
    overtime = max(0, elapsed - limit) if state.overtime_allowed else 0

    if auto_expire and state.running and not state.overtime_allowed and elapsed >= limit:
        if timer is None:
            timer = timer_for(db, room.id, current.id)
        timer.elapsed_seconds = limit
        timer.overtime_seconds = 0
        timer.updated_at = now()
        state.elapsed_seconds = limit
        state.overtime_seconds = 0
        state.running = False
        state.started_at = None
        state.updated_at = now()
        state.completed = False
        db.commit()
        elapsed = limit
        overtime = 0

    remaining = max(0, limit - elapsed)
    awaiting = not state.running and remaining <= 0 and not state.overtime_allowed and not state.completed
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
        "awaiting_decision": awaiting,
        "completed": state.completed,
        "current_speaker": {
            "id": current.id,
            "name": current.name,
            "gender": current.gender,
            "age": current.age,
            "description": current.description,
            "seconds": limit,
        },
    }


def _apply_timer_action_once(db: Session, room: Room, action: str) -> dict:
    state = ensure_room_state(db, room.id)
    speakers = room_speakers(db, room.id, named_only=True)
    current = ensure_current_speaker(db, room, state, speakers)
    if current is None:
        state.running = False
        state.started_at = None
        state.completed = True
        state.updated_at = now()
        db.commit()
        return state_snapshot(db, room)

    timer = timer_for(db, room.id, current.id)
    limit = limit_for(room, current)
    if state.running:
        persist_running_elapsed(state, timer, limit)

    if action in {"next", "prev", "reset"} and state.running:
        raise HTTPException(409, "تا وقتی تایمر در حال اجراست، ابتدا آن را متوقف یا تمام کنید.")

    current_elapsed = timer.elapsed_seconds
    if action == "start":
        if state.completed:
            raise HTTPException(409, "سخنرانی‌ها قبلاً به پایان رسیده‌اند.")
        if current_elapsed >= limit and not state.overtime_allowed:
            raise HTTPException(409, "زمان اصلی این سخنران تمام شده است؛ برای ادامه، «ادامه سخنرانی» را بزنید.")
        state.running = True
        state.started_at = now()

    elif action == "continue":
        if state.completed:
            raise HTTPException(409, "سخنرانی‌ها قبلاً به پایان رسیده‌اند.")
        if current_elapsed < limit:
            raise HTTPException(409, "ادامه فقط پس از پایان زمان اصلی ممکن است.")
        state.overtime_allowed = True
        state.running = True
        state.started_at = now()
        state.completed = False

    elif action == "pause":
        state.running = False
        state.started_at = None
        state.elapsed_seconds = timer.elapsed_seconds
        state.overtime_seconds = max(0, timer.elapsed_seconds - limit) if state.overtime_allowed else 0

    elif action == "reset":
        timer.elapsed_seconds = 0
        timer.overtime_seconds = 0
        timer.updated_at = now()
        state.elapsed_seconds = 0
        state.overtime_seconds = 0
        state.running = False
        state.started_at = None
        state.overtime_allowed = False
        state.completed = False

    elif action in {"next", "prev"}:
        index = speakers.index(current)
        target_index = index + (1 if action == "next" else -1)
        if 0 <= target_index < len(speakers):
            new = speakers[target_index]
            state.current_speaker_id = new.id
            state.current_index = target_index
            state.running = False
            state.started_at = None
            state.overtime_allowed = False
            state.completed = False
            new_timer = timer_for(db, room.id, new.id)
            new_limit = limit_for(room, new)
            state.elapsed_seconds = new_timer.elapsed_seconds
            state.overtime_seconds = max(0, new_timer.elapsed_seconds - new_limit)
            new_timer.overtime_seconds = state.overtime_seconds

    elif action == "finish":
        index = speakers.index(current)
        state.running = False
        state.started_at = None
        state.overtime_allowed = False
        if index + 1 < len(speakers):
            new = speakers[index + 1]
            state.current_speaker_id = new.id
            state.current_index = index + 1
            state.elapsed_seconds = 0
            state.overtime_seconds = 0
            state.completed = False
        else:
            state.completed = True
            state.elapsed_seconds = timer.elapsed_seconds
            state.overtime_seconds = max(0, timer.elapsed_seconds - limit)
            state.current_speaker_id = current.id
            state.current_index = index

    else:
        raise HTTPException(404, "دستور نامعتبر است.")

    state.updated_at = now()
    db.commit()
    return state_snapshot(db, room)


def apply_timer_action(db: Session, room: Room, action: str) -> dict:
    allowed = {"start", "pause", "continue", "reset", "next", "prev", "finish"}
    if action not in allowed:
        raise HTTPException(404, "دستور نامعتبر است.")
    for attempt in range(3):
        try:
            return _apply_timer_action_once(db, room, action)
        except (StaleDataError, IntegrityError, OperationalError):
            db.rollback()
            if attempt == 2:
                raise HTTPException(409, "وضعیت اتاق همزمان تغییر کرد. دوباره تلاش کنید.")
            time.sleep(0.05 * (attempt + 1))
    raise HTTPException(409, "وضعیت اتاق همزمان تغییر کرد.")


def ordered_speakers(speakers: list[Speaker], mode: str, manual_ids: list[int] | None = None) -> list[Speaker]:
    items = list(speakers)
    if mode == "age":
        items.sort(key=lambda s: (s.age is None, s.age if s.age is not None else 10**9, s.id))
    elif mode == "alpha":
        items.sort(key=lambda s: (not bool(s.name), (s.name or "").casefold(), s.id))
    elif mode == "random":
        secrets.SystemRandom().shuffle(items)
    elif mode == "manual":
        mapping = {s.id: s for s in items}
        output = []
        seen = set()
        for sid in manual_ids or []:
            if sid in mapping and sid not in seen:
                output.append(mapping[sid])
                seen.add(sid)
        output.extend(s for s in items if s.id not in seen)
        items = output
    return items


def reserve_room_storage(db: Session, room_id: int, amount: int, maximum: int) -> None:
    if amount <= 0:
        return
    result = db.execute(
        update(Room)
        .where(Room.id == room_id, Room.storage_used_bytes + amount <= maximum)
        .values(storage_used_bytes=Room.storage_used_bytes + amount)
    )
    if result.rowcount != 1:
        raise HTTPException(400, "سهمیهٔ فضای این اتاق پر می‌شود.")


def release_room_storage(db: Session, room_id: int, amount: int) -> None:
    if amount > 0:
        db.execute(update(Room).where(Room.id == room_id).values(storage_used_bytes=func.max(0, Room.storage_used_bytes - amount)))


def collect_room_storage(db: Session, room_id: int) -> list[str]:
    return list(db.scalars(select(SpeechFile.storage_name).where(SpeechFile.room_id == room_id)).all())


def enqueue_cleanup(db: Session, storage_names: list[str]) -> None:
    if not storage_names:
        return
    existing = set(db.scalars(select(FileCleanupQueue.storage_name).where(FileCleanupQueue.storage_name.in_(storage_names))).all())
    for name in storage_names:
        if name and name not in existing:
            db.add(FileCleanupQueue(storage_name=name, attempts=0, next_attempt_at=now(), created_at=now()))


def process_cleanup_queue(db: Session, storage_settings, limit: int = 50) -> int:
    from .storage import safe_storage_path

    rows = db.scalars(
        select(FileCleanupQueue)
        .where(FileCleanupQueue.next_attempt_at <= now())
        .order_by(FileCleanupQueue.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    done = 0
    for row in rows:
        try:
            path = safe_storage_path(storage_settings, row.storage_name)
        except ValueError:
            row.attempts += 1
            row.next_attempt_at = now() + 3600
            continue
        try:
            path.unlink(missing_ok=True)
            db.delete(row)
            done += 1
        except OSError:
            row.attempts += 1
            row.next_attempt_at = now() + min(3600, 2 ** min(row.attempts, 10))
    db.commit()
    return done
