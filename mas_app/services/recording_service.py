"""سرویس ضبط خودکار صدا با پشتیبانی از آپلود تکه‌ای (Chunked) و مونتاژ نهایی سرور.

انطباق کامل با شروط مطرح‌شده توسط کاربر:
- عدم نیاز به دکمهٔ شروع ضبط دستی وقتی ضبط اتاق فعال است.
- سه حالت ضبط: «در حال ضبط»، «متوقف (Paused)»، «اتمام و ذخیره».
- ضبط همگام با تایمر: با حرکت تایمر ضبط فعال است؛ با توقف تایمر یا رسیدن به سقف
  زمان متوقف می‌شود و با ادامهٔ تایمر از سر گرفته می‌شود.
- با اتمام سخنرانی (چه دستی و چه با اتمام زمان) ضبط مونتاژ و ذخیره می‌شود.
- نام‌گذاری فایل‌های ضبط‌شده با فرمت خواسته شده: «نام اتاق - نام سخنران».
"""

from __future__ import annotations

import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..core.errors import NotFoundError, RecordingError
from ..core.security import sanitize_filename
from ..core.timeutil import utc_now_ms
from ..db.models import (
    CleanupQueue,
    RecordingChunk,
    RecordingSession,
    Room,
    Speaker,
    SpeechFile,
)
from ..storage.base import StorageBackend


class RecordingService:
    def __init__(self, settings: Settings, storage: StorageBackend) -> None:
        self.settings = settings
        self.storage = storage

    def get_active_session(
        self, session: Session, room_id: int, speaker_id: int | None = None
    ) -> RecordingSession | None:
        query = select(RecordingSession).where(
            RecordingSession.room_id == room_id,
            RecordingSession.status.in_(["recording", "paused"]),
        )
        if speaker_id is not None:
            query = query.where(RecordingSession.speaker_id == speaker_id)
        return session.execute(query).scalars().first()

    def start_or_resume(
        self,
        session: Session,
        room: Room,
        speaker: Speaker,
        *,
        mime_type: str = "audio/webm",
    ) -> RecordingSession:
        """شروع خودکار یا از سرگیری ضبط برای سخنران فعلی همگام با شروع تایمر."""
        if not room.recording_enabled:
            raise RecordingError("قابلیت ضبط صدا برای این اتاق فعال نیست.")

        rec = self.get_active_session(session, room.id, speaker.id)
        now_ms = utc_now_ms()

        if rec is None:
            # شروع یک نشست ضبط جدید
            sp_name = (speaker.name or "").strip() or f"سخنران {speaker.order_index + 1}"
            rec = RecordingSession(
                room_id=room.id,
                speaker_id=speaker.id,
                speaker_name=sp_name,
                status="recording",
                mime_type=mime_type or "audio/webm",
                chunk_seq=0,
                bytes_received=0,
                recorded_ms=0,
                active_since_ms=now_ms,
                started_at_ms=now_ms,
                last_chunk_at_ms=now_ms,
                ended_at_ms=0,
                error="",
                version=1,
            )
            session.add(rec)
            session.flush()
            return rec

        if rec.status == "paused":
            rec.status = "recording"
            rec.active_since_ms = now_ms
            session.flush()

        return rec

    def pause(self, session: Session, room_id: int, speaker_id: int | None = None) -> None:
        """توقف موقت ضبط همگام با توقف تایمر یا اتمام زمان سخنران."""
        rec = self.get_active_session(session, room_id, speaker_id)
        if not rec or rec.status != "recording":
            return

        now_ms = utc_now_ms()
        if rec.active_since_ms > 0:
            delta = max(0, now_ms - rec.active_since_ms)
            rec.recorded_ms += delta

        rec.active_since_ms = 0
        rec.status = "paused"
        session.flush()

    async def save_chunk(
        self,
        session: Session,
        session_id: int,
        seq: int,
        chunk_data: bytes,
    ) -> RecordingChunk:
        """ذخیرهٔ یک تکه از جریان صوتی در حافظه ذخیره‌سازی و ثبت رکورد آن."""
        rec = session.execute(
            select(RecordingSession).where(RecordingSession.id == session_id)
        ).scalar_one_or_none()
        if not rec:
            raise NotFoundError("نشست ضبط یافت نشد.")

        if rec.status not in ["recording", "paused"]:
            raise RecordingError(f"امکان ارسال تکه برای ضبط در وضعیت {rec.status} وجود ندارد.")

        # سقف تعداد تکه‌ها و حجم کل
        if rec.chunk_seq >= self.settings.recording_max_chunks:
            raise RecordingError("حداکثر تعداد تکه‌های مجاز برای این ضبط پر شده است.")
        if (rec.bytes_received + len(chunk_data)) > self.settings.max_recording_bytes:
            raise RecordingError("حجم کل ضبط از سقف مجاز سرور فراتر رفته است.")

        chunk_key = f"chunks/{rec.room_id}/{rec.id}_{seq:06d}.bin"
        size_bytes, _ = await self.storage.save_bytes(chunk_key, chunk_data)

        chunk = RecordingChunk(
            session_id=rec.id,
            seq=seq,
            storage_key=chunk_key,
            backend=self.settings.storage_backend,
            size_bytes=size_bytes,
            created_at_ms=utc_now_ms(),
        )
        session.add(chunk)

        rec.chunk_seq = max(rec.chunk_seq, seq)
        rec.bytes_received += size_bytes
        rec.last_chunk_at_ms = utc_now_ms()
        session.flush()
        return chunk

    async def finish_and_save(
        self,
        session: Session,
        rec_session: RecordingSession,
    ) -> SpeechFile | None:
        """مونتاژ نهایی تکه‌ها و ساخت فایل ضبط در آرشیو اتاق با فرمت نام استاندارد."""
        if rec_session.status in ["saved", "discarded"]:
            return rec_session.final_file

        now_ms = utc_now_ms()
        if rec_session.status == "recording" and rec_session.active_since_ms > 0:
            rec_session.recorded_ms += max(0, now_ms - rec_session.active_since_ms)
            rec_session.active_since_ms = 0

        # دریافت تکه‌ها به ترتیب
        chunks = session.execute(
            select(RecordingChunk)
            .where(RecordingChunk.session_id == rec_session.id)
            .order_by(RecordingChunk.seq.asc())
        ).scalars().all()

        if not chunks:
            rec_session.status = "discarded"
            rec_session.ended_at_ms = now_ms
            session.flush()
            return None

        room = rec_session.room
        speaker_name = rec_session.speaker_name or "بدون نام"
        # تاریخ شمسی/میلادی ساده برای انتهای نام فایل
        date_str = datetime.datetime.now().strftime("%Y%m%d_%H%M")
        ext = ".weba" if "webm" in rec_session.mime_type else ".m4a"

        # نام‌گذاری دقیق خواسته شده: "نام اتاق - نام سخنران"
        clean_room_name = sanitize_filename(room.name, fallback="اتاق")
        clean_speaker_name = sanitize_filename(speaker_name, fallback="سخنران")
        display_filename = f"{clean_room_name} - {clean_speaker_name} - {date_str}{ext}"

        target_key = f"recordings/{room.id}/{rec_session.id}_{display_filename}"
        chunk_keys = [c.storage_key for c in chunks]

        # مونتاژ فیزیکی
        total_size, sha256_hash = await self.storage.assemble_chunks(target_key, chunk_keys)

        # ایجاد ردیف در speech_files
        speech_file = SpeechFile(
            room_id=room.id,
            speaker_id=rec_session.speaker_id,
            filename=display_filename,
            storage_key=target_key,
            backend=self.settings.storage_backend,
            content_type=rec_session.mime_type,
            size_bytes=total_size,
            upload_type="recording",
            duration_ms=rec_session.recorded_ms,
            speaker_name=speaker_name,
            sha256=sha256_hash,
            created_at_ms=now_ms,
            updated_at_ms=now_ms,
        )
        session.add(speech_file)
        session.flush()

        # به‌روزرسانی وضعیت ضبط
        rec_session.status = "saved"
        rec_session.ended_at_ms = now_ms
        rec_session.final_file_id = speech_file.id

        # افزایش مصرف فضای اتاق و کاربر
        room.storage_used_bytes += total_size
        if room.owner:
            room.owner.storage_used_bytes += total_size

        # صف‌بندی تکه‌های موقت برای حذف قطعی
        for c in chunks:
            session.add(
                CleanupQueue(
                    backend=c.backend,
                    storage_key=c.storage_key,
                    reason="chunk_assembled",
                )
            )

        session.flush()
        return speech_file

    def discard_recording_sync(
        self, session: Session, rec_session: RecordingSession
    ) -> None:
        """دور ریختن ضبط جاری و نشانه‌گذاری تکه‌ها برای حذف."""
        chunks = session.execute(
            select(RecordingChunk).where(RecordingChunk.session_id == rec_session.id)
        ).scalars().all()

        for c in chunks:
            session.add(
                CleanupQueue(
                    backend=c.backend,
                    storage_key=c.storage_key,
                    reason="recording_discarded",
                )
            )

        rec_session.status = "discarded"
        rec_session.ended_at_ms = utc_now_ms()
        session.flush()

    def finish_recording_sync(
        self, session: Session, rec_session: RecordingSession, *, save: bool = True
    ) -> None:
        """نسخهٔ همگام جهت فراخوانی در جریان حذف سخنران."""
        if not save:
            self.discard_recording_sync(session, rec_session)
            return

        # اگر ذخیره خواسته شد ولی در متد همگام هستیم، وضعیت را finalizing می‌گذاریم
        # تا ورکر پس‌زمینه مونتاژ را کامل کند یا بلافاصله به فایل تبدیل شود.
        rec_session.status = "finalizing"
        rec_session.ended_at_ms = utc_now_ms()
        session.flush()
