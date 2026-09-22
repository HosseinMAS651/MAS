"""سرویس مدیریت زمان‌بندی و چرخهٔ عمر تایمر اتاق پخش.

انطباق کامل با شروط مطرح‌شده توسط کاربر:
1. اتمام زمان سخنران:
   به محض رسیدن به سقف زمان، تایمر متوقف می‌شود (`running=False`, `awaiting_decision=True`).
   زمان اضافه فقط و فقط در صورتی محاسبه می‌شود که کاربر گزینهٔ «ادامه سخنرانی» (`continue_overtime`)
   را انتخاب کند.
2. هماهنگی کامل با ضبط صوت:
   - شروع/ادامهٔ تایمر → از سرگیری خودکار ضبط (`start_or_resume`)
   - توقف تایمر یا اتمام زمان → توقف خودکار ضبط (`pause`)
   - اتمام سخنرانی (دستی یا پس از اتمام زمان) → ذخیرهٔ خودکار ضبط (`finish_and_save`)
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.errors import NotFoundError, ValidationAppError
from ..core.timeutil import non_negative_delta, utc_now_ms
from ..db.models import Room, RoomState, Speaker, SpeakerTimerState
from .recording_service import RecordingService

logger = logging.getLogger("mas.timer")


class TimerService:
    def __init__(self, recording_service: RecordingService) -> None:
        self.recording_service = recording_service

    def ensure_room_state(self, session: Session, room: Room) -> RoomState:
        """اطمینان از وجود ردیف RoomState برای اتاق."""
        state = session.execute(
            select(RoomState).where(RoomState.room_id == room.id)
        ).scalar_one_or_none()

        if state is None:
            first_sp = room.speakers[0] if room.speakers else None
            state = RoomState(
                room_id=room.id,
                current_speaker_id=first_sp.id if first_sp else None,
                current_index=0,
                running=False,
                awaiting_decision=False,
                started_at_ms=0,
                elapsed_ms=0,
                overtime_ms=0,
                stop_reason="",
                updated_at_ms=utc_now_ms(),
                version=1,
            )
            session.add(state)
            session.flush()
        return state

    def ensure_speaker_timer(
        self, session: Session, room_id: int, speaker_id: int
    ) -> SpeakerTimerState:
        timer = session.execute(
            select(SpeakerTimerState).where(
                SpeakerTimerState.room_id == room_id,
                SpeakerTimerState.speaker_id == speaker_id,
            )
        ).scalar_one_or_none()

        if timer is None:
            timer = SpeakerTimerState(
                room_id=room_id,
                speaker_id=speaker_id,
                elapsed_ms=0,
                overtime_ms=0,
                started_at_ms=0,
                updated_at_ms=utc_now_ms(),
                version=1,
            )
            session.add(timer)
            session.flush()
        return timer

    def _speaker_limit_ms(self, room: Room, speaker: Speaker) -> int:
        if room.timing_mode == "individual":
            return max(10, speaker.speaking_seconds) * 1000
        return max(10, room.global_seconds) * 1000

    def get_snapshot(
        self, session: Session, room: Room, *, now_ms: int | None = None
    ) -> dict:
        """محاسبهٔ وضعیت بلادرنگ تایمر و اعمال توقف خودکار در زمان اتمام وقت."""
        state = self.ensure_room_state(session, room)
        current_time = utc_now_ms() if now_ms is None else now_ms

        speakers = sorted(room.speakers, key=lambda s: s.order_index)
        current_sp = None
        if state.current_speaker_id:
            current_sp = next((s for s in speakers if s.id == state.current_speaker_id), None)

        if not current_sp and speakers:
            # انتخاب اولین سخنران فریز نشده
            current_sp = next((s for s in speakers if not s.is_finished), speakers[0])
            state.current_speaker_id = current_sp.id
            state.current_index = speakers.index(current_sp)
            session.flush()

        limit_ms = self._speaker_limit_ms(room, current_sp) if current_sp else 300_000
        elapsed = state.elapsed_ms
        overtime = state.overtime_ms

        # بررسی در حال اجرا بودن تایمر
        if state.running and state.started_at_ms > 0:
            delta = non_negative_delta(state.started_at_ms, current_time)

            if not state.awaiting_decision:
                # هنوز در زمان اصلی هستیم
                potential_elapsed = state.elapsed_ms + delta
                if potential_elapsed >= limit_ms:
                    # شرط کاربر: با اتمام زمان، تایمر متوقف می‌شود و در انتظار تصمیم می‌ماند
                    state.running = False
                    state.awaiting_decision = True
                    state.elapsed_ms = limit_ms
                    state.started_at_ms = 0
                    state.stop_reason = "time_up"
                    elapsed = limit_ms
                    overtime = 0

                    # توقف همگام ضبط صوت
                    if room.recording_enabled and current_sp:
                        self.recording_service.pause(session, room.id, current_sp.id)

                    session.flush()
                else:
                    elapsed = potential_elapsed
            else:
                # کاربر دکمهٔ «ادامه سخنرانی» را زده و زمان اضافه در حال محاسبه است
                overtime = state.overtime_ms + delta

        remaining_ms = max(0, limit_ms - elapsed)

        # تعیین وضعیت ضبط برای پاسخ
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
            "remaining_ms": remaining_ms,
            "overtime_ms": overtime,
            "limit_ms": limit_ms,
            "total_speakers": len(speakers),
            "finished_speakers": finished_count,
            "speakers": speakers,
            "recording_status": rec_status,
        }

    async def handle_action(
        self,
        session: Session,
        room: Room,
        action: str,
        *,
        speaker_id: int | None = None,
    ) -> dict:
        """پردازش اکشن‌های کنترل پخش و هماهنگی کامل با ضبط صوت."""
        state = self.ensure_room_state(session, room)
        now_ms = utc_now_ms()

        # ابتدا وضعیت جاری را با زمان حال به‌روز می‌کنیم
        _ = self.get_snapshot(session, room, now_ms=now_ms)

        speakers = sorted(room.speakers, key=lambda s: s.order_index)
        current_sp = next((s for s in speakers if s.id == state.current_speaker_id), None)

        if action == "start":
            if not current_sp:
                raise ValidationAppError("هیچ سخنرانی برای شروع در این اتاق وجود ندارد.")
            if current_sp.is_finished:
                raise ValidationAppError("این سخنران فریز شده است. لطفاً ابتدا او را از فریز خارج کنید.")

            state.running = True
            state.awaiting_decision = False
            state.started_at_ms = now_ms
            state.stop_reason = ""
            state.version += 1

            timer = self.ensure_speaker_timer(session, room.id, current_sp.id)
            timer.started_at_ms = now_ms

            # شروع یا ادامه خودکار ضبط بدون نیاز به کلیک جداگانه
            if room.recording_enabled:
                self.recording_service.start_or_resume(session, room, current_sp)

        elif action == "pause":
            if state.running:
                delta = non_negative_delta(state.started_at_ms, now_ms)
                if state.awaiting_decision:
                    state.overtime_ms += delta
                else:
                    state.elapsed_ms += delta

                state.running = False
                state.started_at_ms = 0
                state.stop_reason = "paused"
                state.version += 1

                if current_sp:
                    timer = self.ensure_speaker_timer(session, room.id, current_sp.id)
                    timer.elapsed_ms = state.elapsed_ms
                    timer.overtime_ms = state.overtime_ms
                    timer.started_at_ms = 0

                # توقف خودکار ضبط
                if room.recording_enabled and current_sp:
                    self.recording_service.pause(session, room.id, current_sp.id)

        elif action == "resume":
            if not current_sp or current_sp.is_finished:
                raise ValidationAppError("امکان از سرگیری وجود ندارد.")

            state.running = True
            state.started_at_ms = now_ms
            state.stop_reason = ""
            state.version += 1

            if room.recording_enabled:
                self.recording_service.start_or_resume(session, room, current_sp)

        elif action == "continue_overtime":
            # شرط کاربر: کاربر انتخاب کرده که سخنرانی با زمان اضافه ادامه یابد
            if not current_sp:
                raise ValidationAppError("سخنرانی یافت نشد.")

            state.running = True
            state.awaiting_decision = True
            state.started_at_ms = now_ms
            state.stop_reason = ""
            state.version += 1

            if room.recording_enabled:
                self.recording_service.start_or_resume(session, room, current_sp)

        elif action in ["finish", "finish_overtime"]:
            # اتمام سخنرانی: چه دستی و چه پس از اتمام زمان
            if current_sp:
                if state.running:
                    delta = non_negative_delta(state.started_at_ms, now_ms)
                    if state.awaiting_decision:
                        state.overtime_ms += delta
                    else:
                        state.elapsed_ms += delta

                current_sp.is_finished = True
                current_sp.finished_at_ms = now_ms
                current_sp.updated_at_ms = now_ms

                timer = self.ensure_speaker_timer(session, room.id, current_sp.id)
                timer.elapsed_ms = state.elapsed_ms
                timer.overtime_ms = state.overtime_ms
                timer.started_at_ms = 0

                # شرط کاربر: با زدن اتمام سخنرانی ضبط ذخیره شود
                if room.recording_enabled:
                    rec = self.recording_service.get_active_session(session, room.id, current_sp.id)
                    if rec:
                        await self.recording_service.finish_and_save(session, rec)

                # انتقال به سخنران بعدی
                next_sp = next(
                    (s for s in speakers[state.current_index + 1 :] if not s.is_finished),
                    None,
                )
                if not next_sp:
                    # بررسی از ابتدا برای سخنران ناتمام دیگر
                    next_sp = next((s for s in speakers if not s.is_finished), None)

                if next_sp:
                    state.current_speaker_id = next_sp.id
                    state.current_index = speakers.index(next_sp)
                    next_timer = self.ensure_speaker_timer(session, room.id, next_sp.id)
                    state.elapsed_ms = next_timer.elapsed_ms
                    state.overtime_ms = next_timer.overtime_ms
                else:
                    state.current_speaker_id = None
                    state.elapsed_ms = 0
                    state.overtime_ms = 0

                state.running = False
                state.awaiting_decision = False
                state.started_at_ms = 0
                state.stop_reason = "finished"
                state.version += 1

        elif action == "reset":
            if current_sp:
                state.running = False
                state.awaiting_decision = False
                state.started_at_ms = 0
                state.elapsed_ms = 0
                state.overtime_ms = 0
                state.stop_reason = ""
                state.version += 1

                timer = self.ensure_speaker_timer(session, room.id, current_sp.id)
                timer.elapsed_ms = 0
                timer.overtime_ms = 0
                timer.started_at_ms = 0

                if room.recording_enabled:
                    rec = self.recording_service.get_active_session(session, room.id, current_sp.id)
                    if rec:
                        self.recording_service.discard_recording_sync(session, rec)

        elif action == "goto":
            if not speaker_id:
                raise ValidationAppError("شناسهٔ سخنران الزامی است.")
            target_sp = next((s for s in speakers if s.id == speaker_id), None)
            if not target_sp:
                raise NotFoundError("سخنران مورد نظر یافت نشد.")

            # توقف ضبط و تایمر سخنران قبلی
            if state.running and current_sp:
                delta = non_negative_delta(state.started_at_ms, now_ms)
                if state.awaiting_decision:
                    state.overtime_ms += delta
                else:
                    state.elapsed_ms += delta
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

        session.flush()
        return self.get_snapshot(session, room, now_ms=now_ms)
