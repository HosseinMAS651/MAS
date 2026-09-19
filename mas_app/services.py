from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import case, delete, select, update
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


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def now() -> int:
    return now_ms() // 1000


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


def normalize_persian(value: str) -> str:
    return (value or "").replace("ي", "ی").replace("ى", "ی").replace("ك", "ک").replace("‌", " ").casefold().strip()


def room_speakers(db: Session, room_id: int, *, named_only: bool = False) -> list[Speaker]:
    stmt = select(Speaker).where(Speaker.room_id == room_id).order_by(Speaker.order_index, Speaker.id)
    if named_only:
        stmt = stmt.where(Speaker.name != "")
    return list(db.scalars(stmt).all())


def ensure_room_state(db: Session, room_id: int, *, lock: bool = False) -> RoomState:
    stmt = select(RoomState).where(RoomState.room_id == room_id)
    if lock:
        stmt = stmt.with_for_update()
    state = db.scalar(stmt)
    if state is None:
        state = RoomState(room_id=room_id, current_index=0, elapsed_seconds=0, overtime_seconds=0, running=False,
                          started_at=None, started_at_ms=None, elapsed_ms=0, overtime_ms=0, updated_at=now(), current_speaker_id=None, version=1)
        db.add(state)
        db.flush()
    return state


def ensure_current_speaker(db: Session, room: Room, state: RoomState, speakers: list[Speaker]) -> Speaker | None:
    if not speakers:
        state.current_speaker_id = None
        state.current_index = 0
        state.running = False
        state.started_at_ms = None
        return None
    ids = {s.id for s in speakers}
    if state.current_speaker_id in ids:
        current = next(s for s in speakers if s.id == state.current_speaker_id)
    else:
        if 0 <= state.current_index < len(speakers):
            current = speakers[state.current_index]
        else:
            current = next((s for s in speakers if not s.is_finished), speakers[0])
        state.current_speaker_id = current.id
        state.running = False
        state.started_at_ms = None
    state.current_index = speakers.index(current)
    if current.is_finished:
        state.running = False
        state.started_at_ms = None
    return current


def timer_limit_ms(room: Room, speaker: Speaker) -> int:
    seconds = room.global_seconds if room.timing_mode == "global" else (speaker.speaking_seconds or room.global_seconds)
    return max(1, int(seconds)) * 1000


def timer_for(db: Session, room_id: int, speaker_id: int, *, lock: bool = True) -> SpeakerTimerState:
    stmt = select(SpeakerTimerState).where(SpeakerTimerState.room_id == room_id, SpeakerTimerState.speaker_id == speaker_id)
    if lock:
        stmt = stmt.with_for_update()
    timer = db.scalar(stmt)
    if timer is None:
        timer = SpeakerTimerState(room_id=room_id, speaker_id=speaker_id, elapsed_seconds=0, overtime_seconds=0,
                                  elapsed_ms=0, overtime_ms=0, updated_at=now(), version=1)
        db.add(timer)
        db.flush()
    return timer


def persist_running_elapsed(state: RoomState, timer: SpeakerTimerState, limit_ms: int) -> None:
    if not state.running or not state.started_at_ms:
        return
    current = now_ms()
    delta = max(0, current - int(state.started_at_ms))
    if delta:
        timer.elapsed_ms = int(timer.elapsed_ms or 0) + delta
        timer.overtime_ms = max(0, timer.elapsed_ms - limit_ms)
        timer.updated_at = current // 1000
    state.elapsed_ms = timer.elapsed_ms
    state.overtime_ms = max(0, timer.elapsed_ms - limit_ms)
    state.elapsed_seconds = timer.elapsed_ms // 1000
    state.overtime_seconds = state.overtime_ms // 1000
    state.started_at_ms = current
    state.updated_at = current // 1000


def timer_values(state: RoomState, timer: SpeakerTimerState, limit_ms: int) -> tuple[int, int, int]:
    elapsed_ms = int(timer.elapsed_ms or 0)
    if state.running and state.started_at_ms:
        elapsed_ms += max(0, now_ms() - int(state.started_at_ms))
    overtime_ms = max(0, elapsed_ms - limit_ms)
    remaining_ms = max(0, limit_ms - elapsed_ms)
    return elapsed_ms, remaining_ms, overtime_ms


def _speaker_payload(speaker: Speaker, limit_ms: int, files: list[SpeechFile] | None = None) -> dict:
    return {
        "id": speaker.id, "name": speaker.name, "gender": speaker.gender, "age": speaker.age,
        "description": speaker.description, "seconds": limit_ms // 1000, "is_finished": bool(speaker.is_finished),
        "finished_at_ms": speaker.finished_at_ms,
        "files": [{"id": f.id, "name": f.filename} for f in (files or [])],
    }


def state_snapshot(db: Session, room: Room) -> dict:
    speakers = room_speakers(db, room.id, named_only=True)
    state = db.scalar(select(RoomState).where(RoomState.room_id == room.id))
    speaker_rows = [
        {"id": s.id, "name": s.name, "is_finished": bool(s.is_finished), "order_index": s.order_index}
        for s in speakers
    ]
    if state is None:
        return {
            "running": False, "current_index": 0, "current_speaker_id": None, "elapsed_ms": 0,
            "remaining_ms": 0, "overtime_ms": 0, "elapsed_seconds": 0, "remaining_seconds": 0,
            "overtime_seconds": 0, "limit_ms": 0, "limit_seconds": 0, "total_speakers": len(speakers),
            "server_time_ms": now_ms(), "version": 0, "current_speaker": None, "speakers": speaker_rows,
        }
    current = ensure_current_speaker(db, room, state, speakers)
    if current is None:
        return {
            "running": False, "current_index": 0, "current_speaker_id": None, "elapsed_ms": 0,
            "remaining_ms": 0, "overtime_ms": 0, "elapsed_seconds": 0, "remaining_seconds": 0,
            "overtime_seconds": 0, "limit_ms": 0, "limit_seconds": 0, "total_speakers": 0,
            "server_time_ms": now_ms(), "version": state.version, "current_speaker": None, "speakers": speaker_rows,
        }
    timer = db.scalar(select(SpeakerTimerState).where(SpeakerTimerState.room_id == room.id, SpeakerTimerState.speaker_id == current.id))
    if timer is None:
        elapsed_ms = overtime_ms = 0
    else:
        limit_ms = timer_limit_ms(room, current)
        elapsed_ms, _remaining_ms, overtime_ms = timer_values(state, timer, limit_ms)
    limit_ms = timer_limit_ms(room, current)
    if timer is not None:
        elapsed_ms, remaining_ms, overtime_ms = timer_values(state, timer, limit_ms)
    else:
        remaining_ms = limit_ms
    current_payload = _speaker_payload(current, limit_ms, list(current.files) if hasattr(current, "files") else [])
    return {
        "running": bool(state.running), "current_index": speakers.index(current), "current_speaker_id": current.id,
        "elapsed_ms": elapsed_ms, "remaining_ms": remaining_ms, "overtime_ms": overtime_ms,
        "elapsed_seconds": elapsed_ms // 1000, "remaining_seconds": remaining_ms // 1000,
        "overtime_seconds": overtime_ms // 1000, "limit_ms": limit_ms, "limit_seconds": limit_ms // 1000,
        "total_speakers": len(speakers), "server_time_ms": now_ms(), "version": state.version,
        "current_speaker": current_payload, "speakers": speaker_rows,
    }


def _apply_timer_action_once(db: Session, room: Room, action: str) -> dict:
    state = ensure_room_state(db, room.id, lock=True)
    speakers = room_speakers(db, room.id, named_only=True)
    current = ensure_current_speaker(db, room, state, speakers)
    if current is None:
        db.commit()
        return state_snapshot(db, room)

    timer = timer_for(db, room.id, current.id, lock=True)
    limit_ms = timer_limit_ms(room, current)
    if state.running:
        persist_running_elapsed(state, timer, limit_ms)

    if action == "start":
        if current.is_finished:
            raise HTTPException(400, "این سخنرانی پایان یافته و فریز شده است.")
        if not state.running:
            state.running = True
            state.started_at_ms = now_ms()
    elif action == "pause":
        state.running = False
        state.started_at_ms = None
    elif action == "reset":
        if current.is_finished:
            raise HTTPException(400, "سخنران فریز شده است.")
        timer.elapsed_ms = 0
        timer.overtime_ms = 0
        timer.elapsed_seconds = 0
        timer.overtime_seconds = 0
        timer.updated_at = now()
        state.elapsed_ms = 0
        state.overtime_ms = 0
        state.elapsed_seconds = 0
        state.overtime_seconds = 0
        state.running = False
        state.started_at_ms = None
    elif action == "continue_overtime":
        if current.is_finished:
            raise HTTPException(400, "این سخنرانی پایان یافته است.")
        state.running = True
        state.started_at_ms = now_ms()
    elif action == "finish":
        current.is_finished = True
        current.finished_at_ms = now_ms()
        state.running = False
        state.started_at_ms = None
        state.elapsed_ms = timer.elapsed_ms
        state.overtime_ms = max(0, timer.elapsed_ms - limit_ms)
        state.elapsed_seconds = timer.elapsed_ms // 1000
        state.overtime_seconds = state.overtime_ms // 1000
    elif action in {"next", "prev"}:
        if not speakers:
            state.running = False
            state.started_at_ms = None
        else:
            current_idx = speakers.index(current)
            new_idx = None
            if action == "next":
                for idx in range(current_idx + 1, len(speakers)):
                    if not speakers[idx].is_finished:
                        new_idx = idx
                        break
            else:
                if current_idx > 0:
                    new_idx = current_idx - 1
            if new_idx is not None:
                new_speaker = speakers[new_idx]
                state.current_speaker_id = new_speaker.id
                state.current_index = new_idx
                state.running = False
                state.started_at_ms = None
                new_timer = timer_for(db, room.id, new_speaker.id, lock=True)
                new_limit = timer_limit_ms(room, new_speaker)
                new_timer.overtime_ms = max(0, new_timer.elapsed_ms - new_limit)
                new_timer.elapsed_seconds = new_timer.elapsed_ms // 1000
                new_timer.overtime_seconds = new_timer.overtime_ms // 1000
                state.elapsed_ms = new_timer.elapsed_ms
                state.overtime_ms = new_timer.overtime_ms
                state.elapsed_seconds = new_timer.elapsed_seconds
                state.overtime_seconds = new_timer.overtime_seconds
            else:
                state.running = False
                state.started_at_ms = None
    else:
        raise HTTPException(404, "دستور نامعتبر است.")

    state.updated_at = now()
    db.commit()
    return state_snapshot(db, room)



def goto_speaker(db: Session, room: Room, speaker_id: int) -> dict:
    state = ensure_room_state(db, room.id, lock=True)
    speakers = room_speakers(db, room.id, named_only=True)
    target = next((s for s in speakers if s.id == speaker_id), None)
    if target is None:
        raise HTTPException(404, "سخنران پیدا نشد.")
    current = ensure_current_speaker(db, room, state, speakers)
    if current is not None and state.running:
        current_timer = timer_for(db, room.id, current.id, lock=True)
        persist_running_elapsed(state, current_timer, timer_limit_ms(room, current))
    state.current_speaker_id = target.id
    state.current_index = speakers.index(target)
    state.running = False
    state.started_at_ms = None
    target_timer = timer_for(db, room.id, target.id, lock=True)
    limit = timer_limit_ms(room, target)
    target_timer.overtime_ms = max(0, int(target_timer.elapsed_ms or 0) - limit)
    target_timer.elapsed_seconds = int(target_timer.elapsed_ms or 0) // 1000
    target_timer.overtime_seconds = int(target_timer.overtime_ms or 0) // 1000
    state.elapsed_ms = int(target_timer.elapsed_ms or 0)
    state.overtime_ms = int(target_timer.overtime_ms or 0)
    state.elapsed_seconds = state.elapsed_ms // 1000
    state.overtime_seconds = state.overtime_ms // 1000
    state.updated_at = now()
    db.commit()
    return state_snapshot(db, room)

def apply_timer_action(db: Session, room: Room, action: str) -> dict:
    allowed = {"start", "pause", "reset", "next", "prev", "finish", "continue_overtime"}
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
    mode = mode if mode in ORDER_MODES else "manual"
    if mode == "age":
        items.sort(key=lambda s: (s.age is None, s.age if s.age is not None else 10**9, s.id))
    elif mode == "alpha":
        items.sort(key=lambda s: (not bool(s.name), normalize_persian(s.name), s.id))
    elif mode == "random":
        secrets.SystemRandom().shuffle(items)
    else:
        mapping = {s.id: s for s in items}
        ordered: list[Speaker] = []
        seen: set[int] = set()
        for sid in manual_ids or []:
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
    result = db.execute(update(Room).where(Room.id == room_id, Room.storage_used_bytes + amount <= maximum).values(storage_used_bytes=Room.storage_used_bytes + amount))
    if result.rowcount != 1:
        raise HTTPException(400, "سهمیهٔ فضای این اتاق پر می‌شود.")


def release_room_storage(db: Session, room_id: int, amount: int) -> None:
    if amount <= 0:
        return
    new_value = case((Room.storage_used_bytes > amount, Room.storage_used_bytes - amount), else_=0)
    db.execute(update(Room).where(Room.id == room_id).values(storage_used_bytes=new_value))


def collect_room_storage(db: Session, room_id: int) -> list[str]:
    return list(db.scalars(select(SpeechFile.storage_name).where(SpeechFile.room_id == room_id)).all())


def collect_speaker_storage(db: Session, speaker_id: int) -> tuple[list[str], int]:
    rows = db.scalars(select(SpeechFile).where(SpeechFile.speaker_id == speaker_id)).all()
    return [x.storage_name for x in rows], sum(int(x.size_bytes or 0) for x in rows)


def enqueue_cleanup(db: Session, storage_names: list[str]) -> None:
    for name in storage_names:
        if not name:
            continue
        exists = db.scalar(select(FileCleanupQueue.id).where(FileCleanupQueue.storage_name == name))
        if exists is None:
            db.add(FileCleanupQueue(storage_name=name, attempts=0, next_attempt_at=now(), created_at=now()))


def process_cleanup_queue(db: Session, storage_settings, limit: int = 50) -> int:
    rows = db.scalars(
        select(FileCleanupQueue).where(FileCleanupQueue.next_attempt_at <= now()).order_by(FileCleanupQueue.id).limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    processed = 0
    for row in rows:
        try:
            still_referenced = db.scalar(select(SpeechFile.id).where(SpeechFile.storage_name == row.storage_name))
            if still_referenced is not None:
                db.delete(row)
                processed += 1
                continue
            path = safe_storage_path(storage_settings, row.storage_name)
            path.unlink(missing_ok=True)
            db.delete(row)
            processed += 1
        except (OSError, ValueError):
            row.attempts += 1
            row.next_attempt_at = int(time.time() + min(3600, 2 ** min(row.attempts, 10)))
    db.commit()
    return processed
