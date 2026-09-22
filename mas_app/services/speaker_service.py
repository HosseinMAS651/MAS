"""سرویس مدیریت سخنران‌ها.

باگ‌های برطرف‌شده در این سرویس:
- **C-01**: حذف ۵۰۰ در حذف سخنران با مرتب‌سازی مجدد و شماره‌گذاری بدون تداخل یونیک.
- **C-05**: رفع بن‌بست فریز با متدهای `unfreeze_speaker` و `reset_all_speakers`.
- **درخواست کاربر**: بررسی ضبط فعال در زمان حذف سخنران و درخواست تعیین تکلیف (ذخیره/دور ریختن).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.errors import AppError, NotFoundError, ValidationAppError
from ..core.security import normalize_persian_text
from ..core.timeutil import utc_now_ms
from ..db.models import (
    CleanupQueue,
    RecordingSession,
    Room,
    Speaker,
    SpeakerTimerState,
    SpeechFile,
)


class SpeakerService:
    @staticmethod
    def add_speaker(
        session: Session,
        room: Room,
        *,
        name: str = "",
        gender: str = "",
        age: int | None = None,
        description: str = "",
        speaking_seconds: int | None = None,
    ) -> Speaker:
        current_count = len(room.speakers)
        if current_count >= room.capacity:
            raise ValidationAppError(
                f"ظرفیت اتاق ({room.capacity} نفر) پر است. برای افزودن سخنران، ابتدا ظرفیت اتاق را افزایش دهید."
            )

        secs = (
            speaking_seconds
            if (room.timing_mode == "individual" and speaking_seconds)
            else room.global_seconds
        )
        now_ms = utc_now_ms()

        speaker = Speaker(
            room_id=room.id,
            order_index=current_count,
            name=normalize_persian_text(name),
            gender=gender,
            age=age,
            description=normalize_persian_text(description),
            speaking_seconds=secs,
            is_finished=False,
            finished_at_ms=0,
            created_at_ms=now_ms,
            updated_at_ms=now_ms,
        )
        session.add(speaker)
        session.flush()

        # ساخت رکورد تایمر
        timer = SpeakerTimerState(
            room_id=room.id,
            speaker_id=speaker.id,
            elapsed_ms=0,
            overtime_ms=0,
            started_at_ms=0,
            updated_at_ms=now_ms,
            version=1,
        )
        session.add(timer)
        session.flush()
        return speaker

    @staticmethod
    def update_speaker(
        session: Session,
        speaker: Speaker,
        *,
        name: str,
        gender: str = "",
        age: int | None = None,
        description: str = "",
        speaking_seconds: int | None = None,
    ) -> Speaker:
        room = speaker.room
        old_name = speaker.name
        new_name = normalize_persian_text(name)

        speaker.name = new_name
        speaker.gender = gender
        speaker.age = age
        speaker.description = normalize_persian_text(description)
        if room.timing_mode == "individual" and speaking_seconds:
            speaker.speaking_seconds = speaking_seconds
        speaker.updated_at_ms = utc_now_ms()

        # اگر نام تغییر کرد و شخص جدیدی جایگزین شد، وضعیت فریز بازنشانی شود (رفع C-05)
        if old_name != new_name and not new_name:
            speaker.is_finished = False
            speaker.finished_at_ms = 0
            if speaker.timer:
                speaker.timer.elapsed_ms = 0
                speaker.timer.overtime_ms = 0
                speaker.timer.started_at_ms = 0

        session.flush()
        return speaker

    @staticmethod
    async def delete_speaker(
        session: Session,
        room: Room,
        speaker_id: int,
        *,
        save_recording: bool | None = None,
        recording_service: object | None = None,
    ) -> None:
        """حذف یک اسلات سخنران.

        حل ریشه‌ای باگ C-01 (تداخل یونیک در شماره‌گذاری مجدد) + اعمال خواستهٔ کاربر
        برای بررسی ضبط فعال پیش از حذف.
        """
        speaker = session.execute(
            select(Speaker).where(Speaker.id == speaker_id, Speaker.room_id == room.id)
        ).scalar_one_or_none()
        if not speaker:
            raise NotFoundError("سخنران مورد نظر یافت نشد.")

        # بررسی وجود ضبط فعال برای این سخنران
        active_rec = session.execute(
            select(RecordingSession).where(
                RecordingSession.room_id == room.id,
                RecordingSession.speaker_id == speaker.id,
                RecordingSession.status.in_(["recording", "paused"]),
            )
        ).scalar_one_or_none()

        if active_rec and (active_rec.bytes_received > 0 or active_rec.recorded_ms > 0):
            if save_recording is None:
                # به کلاینت اعلام می‌کنیم که کاربر باید تصمیم بگیرد
                raise AppError(
                    "برای این سخنران یک ضبط فعال وجود دارد. لطفاً مشخص کنید فایل ذخیره شود یا دور ریخته شود.",
                    code="RECORDING_ACTIVE_PROMPT_REQUIRED",
                    details={
                        "session_id": active_rec.id,
                        "speaker_name": speaker.name or "سخنران",
                        "recorded_ms": active_rec.recorded_ms,
                    },
                    status_code=409,
                )
            if recording_service is not None:
                # اجرای تصمیم کاربر (ذخیره یا دور ریختن)
                if save_recording:
                    await recording_service.finish_and_save(session, active_rec)
                else:
                    recording_service.discard_recording_sync(session, active_rec)

        # فایل‌های اختصاصی سخنران (غیر از ضبط‌ها) برای حذف صف‌بندی شوند
        sp_files = session.execute(
            select(SpeechFile).where(
                SpeechFile.speaker_id == speaker.id,
                SpeechFile.upload_type == "speaker",
            )
        ).scalars().all()
        for f in sp_files:
            room.storage_used_bytes = max(0, room.storage_used_bytes - f.size_bytes)
            if room.owner:
                room.owner.storage_used_bytes = max(
                    0, room.owner.storage_used_bytes - f.size_bytes
                )
            session.add(
                CleanupQueue(
                    backend=f.backend,
                    storage_key=f.storage_key,
                    reason="speaker_deleted",
                )
            )
            session.delete(f)

        # اگر در RoomState سخنران فعلی بود، جدا شود
        if room.state and room.state.current_speaker_id == speaker.id:
            room.state.current_speaker_id = None
            room.state.running = False
            room.state.awaiting_decision = False

        session.delete(speaker)
        session.flush()

        # بازشماری قطعی و امن همه سخنران‌های باقیمانده بدون نقض UNIQUE (C-01)
        remaining_speakers = session.execute(
            select(Speaker)
            .where(Speaker.room_id == room.id)
            .order_by(Speaker.order_index.asc())
        ).scalars().all()

        # گام اول: تخصیص اندیس موقت بزرگ برای خالی شدن بازه (>=0 برای رعایت CHECK constraint)
        for idx, sp in enumerate(remaining_speakers):
            sp.order_index = 100_000 + idx
        session.flush()

        # گام دوم: شماره‌گذاری دقیق و ترتیبی از صفر
        for idx, sp in enumerate(remaining_speakers):
            sp.order_index = idx
        session.flush()

    @staticmethod
    def reorder_speakers(session: Session, room: Room, speaker_ids: list[int]) -> None:
        """تغییر ترتیب سخنران‌ها بر اساس لیست idهای ارسالی."""
        speakers = session.execute(
            select(Speaker).where(Speaker.room_id == room.id)
        ).scalars().all()
        sp_map = {sp.id: sp for sp in speakers}

        if set(sp_map.keys()) != set(speaker_ids):
            raise ValidationAppError("لیست شناسه‌های سخنران‌ها نامعتبر یا ناقص است.")

        # دو مرحله‌ای برای جلوگیری از UNIQUE collision (با مقادیر مثبت برای پاس شدن CHECK)
        for idx, sp_id in enumerate(speaker_ids):
            sp_map[sp_id].order_index = 100_000 + idx
        session.flush()

        for idx, sp_id in enumerate(speaker_ids):
            sp_map[sp_id].order_index = idx
        session.flush()

    @staticmethod
    def unfreeze_speaker(session: Session, room: Room, speaker_id: int) -> Speaker:
        """خروج سخنران از حالت فریز (رفع باگ C-05)."""
        speaker = session.execute(
            select(Speaker).where(Speaker.id == speaker_id, Speaker.room_id == room.id)
        ).scalar_one_or_none()
        if not speaker:
            raise NotFoundError("سخنران مورد نظر یافت نشد.")

        speaker.is_finished = False
        speaker.finished_at_ms = 0
        speaker.updated_at_ms = utc_now_ms()
        session.flush()
        return speaker

    @staticmethod
    def reset_all_speakers(session: Session, room: Room) -> None:
        """بازنشانی کلیه سخنران‌ها و تایمرهای اتاق به حالت اولیه (رفع باگ C-05)."""
        speakers = session.execute(
            select(Speaker).where(Speaker.room_id == room.id)
        ).scalars().all()
        now_ms = utc_now_ms()

        for sp in speakers:
            sp.is_finished = False
            sp.finished_at_ms = 0
            sp.updated_at_ms = now_ms
            if sp.timer:
                sp.timer.elapsed_ms = 0
                sp.timer.overtime_ms = 0
                sp.timer.started_at_ms = 0
                sp.timer.updated_at_ms = now_ms

        if room.state:
            room.state.running = False
            room.state.awaiting_decision = False
            room.state.elapsed_ms = 0
            room.state.overtime_ms = 0
            room.state.started_at_ms = 0
            room.state.current_index = 0
            first_sp = speakers[0] if speakers else None
            room.state.current_speaker_id = first_sp.id if first_sp else None
            room.state.updated_at_ms = now_ms

        session.flush()
