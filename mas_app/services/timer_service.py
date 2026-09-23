"""Concurrency-safe room timer state machine."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.errors import ConflictError, NotFoundError, ValidationAppError
from ..core.timeutil import non_negative_delta, utc_now_ms
from ..db.models import Room, RoomState, Speaker, SpeakerTimerState
from .recording_service import RecordingService


class TimerService:
    def __init__(self, recording_service: RecordingService) -> None:
        self.recording_service = recording_service

    def ensure_room_state(self, session: Session, room: Room) -> RoomState:
        state = session.execute(select(RoomState).where(RoomState.room_id == room.id)).scalar_one_or_none()
        if state is None:
            first_sp = sorted(room.speakers, key=lambda s: s.order_index)[0] if room.speakers else None
            state = RoomState(
                room_id=room.id,
                current_speaker_id=first_sp.id if first_sp else None,
                current_index=0,
                running=False, awaiting_decision=False, started_at_ms=0, elapsed_ms=0, overtime_ms=0,
                stop_reason="", updated_at_ms=utc_now_ms(), version=1,
            )
            session.add(state)
            session.flush()
        return state

    def _lock_state(self, session: Session, room: Room) -> RoomState:
        state = session.execute(select(RoomState).where(RoomState.room_id == room.id).with_for_update()).scalar_one_or_none()
        if state is None:
            state = self.ensure_room_state(session, room)
        return state

    def ensure_speaker_timer(self, session: Session, room_id: int, speaker_id: int) -> SpeakerTimerState:
        timer = session.execute(
            select(SpeakerTimerState).where(SpeakerTimerState.room_id == room_id, SpeakerTimerState.speaker_id == speaker_id)
        ).scalar_one_or_none()
        if timer is None:
            timer = SpeakerTimerState(room_id=room_id, speaker_id=speaker_id, elapsed_ms=0, overtime_ms=0, started_at_ms=0, updated_at_ms=utc_now_ms(), version=1)
            session.add(timer)
            session.flush()
        return timer

    def _speaker_limit_ms(self, room: Room, speaker: Speaker) -> int:
        return (speaker.speaking_seconds if room.timing_mode == "individual" else room.global_seconds) * 1000

    def _sync_current_timer(self, session: Session, state: RoomState, room: Room, speaker: Speaker, now_ms: int) -> None:
        if state.running and state.started_at_ms > 0:
            delta = non_negative_delta(state.started_at_ms, now_ms)
            if state.awaiting_decision:
                state.overtime_ms += delta
            else:
                state.elapsed_ms += delta
        timer = self.ensure_speaker_timer(session, room.id, speaker.id)
        timer.elapsed_ms = state.elapsed_ms
        timer.overtime_ms = state.overtime_ms
        timer.started_at_ms = 0
        timer.updated_at_ms = now_ms
        timer.version += 1

    def _current_speaker(self, room: Room, state: RoomState) -> Speaker | None:
        speakers = sorted(room.speakers, key=lambda s: s.order_index)
        if state.current_speaker_id is not None:
            sp = next((s for s in speakers if s.id == state.current_speaker_id), None)
            if sp:
                return sp
        return next((s for s in speakers if not s.is_finished), speakers[0] if speakers else None)

    def get_snapshot(self, session: Session, room: Room, *, now_ms: int | None = None) -> dict:
        state = self.ensure_room_state(session, room)
        current_time = utc_now_ms() if now_ms is None else now_ms
        speakers = sorted(room.speakers, key=lambda s: s.order_index)
        current_sp = self._current_speaker(room, state)
        if current_sp and state.current_speaker_id != current_sp.id:
            state.current_speaker_id = current_sp.id
            state.current_index = speakers.index(current_sp)
            timer = self.ensure_speaker_timer(session, room.id, current_sp.id)
            state.elapsed_ms = timer.elapsed_ms
            state.overtime_ms = timer.overtime_ms
            state.version += 1

        limit_ms = self._speaker_limit_ms(room, current_sp) if current_sp else 300_000
        elapsed = state.elapsed_ms
        overtime = state.overtime_ms
        if state.running and state.started_at_ms > 0:
            delta = non_negative_delta(state.started_at_ms, current_time)
            if state.awaiting_decision:
                overtime = state.overtime_ms + delta
            else:
                potential_elapsed = state.elapsed_ms + delta
                if potential_elapsed >= limit_ms:
                    state.running = False
                    state.awaiting_decision = True
                    state.elapsed_ms = limit_ms
                    state.started_at_ms = 0
                    state.stop_reason = "time_up"
                    elapsed = limit_ms
                    overtime = 0
                    state.version += 1
                    if current_sp:
                        timer = self.ensure_speaker_timer(session, room.id, current_sp.id)
                        timer.elapsed_ms = limit_ms
                        timer.overtime_ms = state.overtime_ms
                        timer.started_at_ms = 0
                        timer.updated_at_ms = current_time
                        timer.version += 1
                        if room.recording_enabled:
                            self.recording_service.pause(session, room.id, current_sp.id)
                    session.flush()
                else:
                    elapsed = potential_elapsed

        rec_status = "inactive"
        if room.recording_enabled and current_sp:
            rec = self.recording_service.get_active_session(session, room.id, current_sp.id)
            if rec:
                rec_status = rec.status

        finished_count = sum(1 for s in speakers if s.is_finished)
        return {
            "room_id": room.id,
            "version": state.version,
            "running": state.running,
            "awaiting_decision": state.awaiting_decision,
            "stop_reason": state.stop_reason,
            "current_index": state.current_index,
            "current_speaker_id": current_sp.id if current_sp else None,
            "current_speaker": current_sp,
            "elapsed_ms": elapsed,
            "remaining_ms": max(0, limit_ms - elapsed),
            "overtime_ms": overtime,
            "limit_ms": limit_ms,
            "total_speakers": len(speakers),
            "finished_speakers": finished_count,
            "speakers": speakers,
            "recording_status": rec_status,
        }

    async def handle_action(self, session: Session, room: Room, action: str, *, speaker_id: int | None = None, expected_version: int | None = None) -> dict:
        state = self._lock_state(session, room)
        now_ms = utc_now_ms()
        self.get_snapshot(session, room, now_ms=now_ms)
        if expected_version is not None and state.version != expected_version:
            raise ConflictError("وضعیت اتاق تغییر کرده است؛ لطفاً اطلاعات اتاق را تازه‌سازی کنید.", code="STATE_VERSION_CONFLICT", details={"current_version": state.version})

        speakers = sorted(room.speakers, key=lambda s: s.order_index)
        current_sp = self._current_speaker(room, state)
        if current_sp and state.current_speaker_id != current_sp.id:
            state.current_speaker_id = current_sp.id
            state.current_index = speakers.index(current_sp)

        if action == "start":
            if not current_sp:
                raise ValidationAppError("هیچ سخنرانی برای شروع در این اتاق وجود ندارد.")
            if current_sp.is_finished:
                raise ValidationAppError("این سخنران پایان یافته است. ابتدا او را از فریز خارج کنید.")
            if state.running:
                raise ConflictError("تایمر در حال اجراست.", code="TIMER_ALREADY_RUNNING")
            if state.awaiting_decision:
                raise ValidationAppError("ابتدا دربارهٔ ادامهٔ زمان اضافه تصمیم بگیرید.")
            state.running = True
            state.started_at_ms = now_ms
            state.stop_reason = ""
            state.version += 1
            if room.recording_enabled:
                self.recording_service.start_or_resume(session, room, current_sp)

        elif action == "pause":
            if state.running and current_sp:
                self._sync_current_timer(session, state, room, current_sp, now_ms)
                state.running = False
                state.started_at_ms = 0
                state.stop_reason = "paused"
                state.version += 1
                if room.recording_enabled:
                    self.recording_service.pause(session, room.id, current_sp.id)

        elif action == "resume":
            if not current_sp or current_sp.is_finished:
                raise ValidationAppError("امکان از سرگیری وجود ندارد.")
            if state.running:
                raise ConflictError("تایمر در حال اجراست.", code="TIMER_ALREADY_RUNNING")
            if state.awaiting_decision:
                raise ValidationAppError("برای ادامهٔ زمان اضافه از گزینهٔ «ادامه» استفاده کنید.")
            state.running = True
            state.started_at_ms = now_ms
            state.stop_reason = ""
            state.version += 1
            if room.recording_enabled:
                self.recording_service.start_or_resume(session, room, current_sp)

        elif action == "continue_overtime":
            if not current_sp:
                raise ValidationAppError("سخنرانی یافت نشد.")
            if not state.awaiting_decision:
                raise ValidationAppError("در حال حاضر تصمیمی برای زمان اضافه مورد نیاز نیست.")
            if current_sp.is_finished:
                raise ValidationAppError("این سخنران پایان یافته است.")
            state.running = True
            state.awaiting_decision = True
            state.started_at_ms = now_ms
            state.stop_reason = ""
            state.version += 1
            if room.recording_enabled:
                self.recording_service.start_or_resume(session, room, current_sp)

        elif action in ("finish", "finish_overtime"):
            if not current_sp:
                raise ValidationAppError("سخنرانی فعلی یافت نشد.")
            self._sync_current_timer(session, state, room, current_sp, now_ms)
            current_sp.is_finished = True
            current_sp.finished_at_ms = now_ms
            current_sp.updated_at_ms = now_ms
            if room.recording_enabled:
                rec = self.recording_service.get_active_session(session, room.id, current_sp.id, lock=True)
                if rec:
                    await self.recording_service.finish_and_save(session, rec)
            remaining = [s for s in speakers if not s.is_finished and s.id != current_sp.id]
            next_sp = next((s for s in remaining if s.order_index > current_sp.order_index), None) or (remaining[0] if remaining else None)
            if next_sp:
                next_timer = self.ensure_speaker_timer(session, room.id, next_sp.id)
                state.current_speaker_id = next_sp.id
                state.current_index = speakers.index(next_sp)
                state.elapsed_ms = next_timer.elapsed_ms
                state.overtime_ms = next_timer.overtime_ms
            else:
                state.current_speaker_id = None
                state.current_index = 0
                state.elapsed_ms = 0
                state.overtime_ms = 0
            state.running = False
            state.awaiting_decision = False
            state.started_at_ms = 0
            state.stop_reason = "finished"
            state.version += 1

        elif action == "reset":
            if current_sp:
                if room.recording_enabled:
                    rec = self.recording_service.get_active_session(session, room.id, current_sp.id, lock=True)
                    if rec:
                        self.recording_service.discard_recording_sync(session, rec)
                state.running = False
                state.awaiting_decision = False
                state.started_at_ms = 0
                state.elapsed_ms = 0
                state.overtime_ms = 0
                state.stop_reason = ""
                timer = self.ensure_speaker_timer(session, room.id, current_sp.id)
                timer.elapsed_ms = timer.overtime_ms = timer.started_at_ms = 0
                timer.updated_at_ms = now_ms
                timer.version += 1
                state.version += 1

        elif action == "goto":
            if speaker_id is None:
                raise ValidationAppError("شناسهٔ سخنران الزامی است.")
            target_sp = next((s for s in speakers if s.id == speaker_id), None)
            if not target_sp:
                raise NotFoundError("سخنران مورد نظر یافت نشد.")
            if current_sp and current_sp.id != target_sp.id:
                self._sync_current_timer(session, state, room, current_sp, now_ms)
                if room.recording_enabled:
                    self.recording_service.pause(session, room.id, current_sp.id)
            target_timer = self.ensure_speaker_timer(session, room.id, target_sp.id)
            state.current_speaker_id = target_sp.id
            state.current_index = speakers.index(target_sp)
            state.elapsed_ms = target_timer.elapsed_ms
            state.overtime_ms = target_timer.overtime_ms
            state.running = False
            state.awaiting_decision = False
            state.started_at_ms = 0
            state.stop_reason = "switched"
            state.version += 1

        else:
            raise ValidationAppError("دستور تایمر نامعتبر است.")

        state.updated_at_ms = now_ms
        session.flush()
        return self.get_snapshot(session, room, now_ms=now_ms)
