"""Reliable automatic audio recording service with ordered chunks and safe finalization."""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..core.errors import ConflictError, NotFoundError, QuotaExceededError, RecordingError
from ..core.security import sanitize_filename
from ..core.timeutil import utc_now_ms
from ..db.models import RecordingChunk, RecordingSession, Room, Speaker, SpeechFile, User
from ..storage.base import StorageBackend
from .cleanup_queue import enqueue_cleanup


class RecordingService:
    ACTIVE_STATUSES = ("recording", "paused")
    BLOCKING_STATUSES = ("recording", "paused", "finalizing")

    def __init__(self, settings: Settings, storage: StorageBackend) -> None:
        self.settings = settings
        self.storage = storage

    def _lock_room(self, session: Session, room_id: int) -> Room:
        room = session.execute(
            select(Room).where(Room.id == room_id).with_for_update()
        ).scalar_one_or_none()
        if not room:
            raise NotFoundError("اتاق مورد نظر یافت نشد.")
        return room

    def get_active_session(
        self,
        session: Session,
        room_id: int,
        speaker_id: int | None = None,
        *,
        lock: bool = False,
        include_finalizing: bool = False,
    ) -> RecordingSession | None:
        statuses = self.BLOCKING_STATUSES if include_finalizing else self.ACTIVE_STATUSES
        query = (
            select(RecordingSession)
            .where(
                RecordingSession.room_id == room_id,
                RecordingSession.status.in_(statuses),
            )
            .order_by(RecordingSession.id.desc())
        )
        if speaker_id is not None:
            query = query.where(RecordingSession.speaker_id == speaker_id)
        if lock:
            query = query.with_for_update()
        return session.execute(query).scalars().first()

    @staticmethod
    def normalize_mime_type(mime_type: str | None) -> str:
        mime = (mime_type or "").split(";", 1)[0].strip().lower()
        return mime if mime in {
            "audio/webm", "audio/mp4", "audio/ogg", "audio/wav", "audio/x-wav",
            "audio/mpeg", "audio/aac", "audio/flac",
        } else "audio/webm"

    def start_or_resume(
        self,
        session: Session,
        room: Room,
        speaker: Speaker,
        *,
        mime_type: str = "audio/webm",
    ) -> RecordingSession:
        if not (room.recording_enabled or room.speaker_mode_enabled):
            raise RecordingError("قابلیت ضبط صدا برای این اتاق فعال نیست.")

        normalized_mime = self.normalize_mime_type(mime_type)
        locked_room = self._lock_room(session, room.id)
        blocking = self.get_active_session(
            session, locked_room.id, speaker.id, lock=True, include_finalizing=True
        )
        if blocking and blocking.status == "finalizing":
            raise ConflictError(
                "ضبط دیگری در حال ذخیره‌سازی است؛ لطفاً کمی بعد دوباره تلاش کنید.",
                code="RECORDING_FINALIZING",
            )
        if blocking and blocking.speaker_id != speaker.id:
            raise ConflictError(
                "هم‌زمان فقط ضبط یک سخنران امکان‌پذیر است.",
                code="ACTIVE_RECORDING_EXISTS",
            )

        rec = blocking
        now_ms = utc_now_ms()
        if rec is None:
            sp_name = (speaker.name or "").strip() or f"سخنران {speaker.order_index + 1}"
            rec = RecordingSession(
                room_id=locked_room.id,
                speaker_id=speaker.id,
                speaker_name=sp_name[:120],
                status="recording",
                mime_type=normalized_mime,
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

        if rec.chunk_seq == 0:
            rec.mime_type = normalized_mime

        if rec.status == "paused":
            rec.status = "recording"
            rec.active_since_ms = now_ms
            rec.error = ""
            rec.version += 1
            session.flush()
        return rec

    def pause(self, session: Session, room_id: int, speaker_id: int | None = None) -> None:
        rec = self.get_active_session(session, room_id, speaker_id, lock=True)
        if not rec or rec.status != "recording":
            return
        now_ms = utc_now_ms()
        if rec.active_since_ms > 0:
            rec.recorded_ms += max(0, now_ms - rec.active_since_ms)
        rec.recorded_ms = min(rec.recorded_ms, self.settings.max_recording_seconds * 1000)
        rec.active_since_ms = 0
        rec.status = "paused"
        rec.version += 1
        session.flush()

    async def save_chunk(
        self,
        session: Session,
        session_id: int,
        seq: int,
        chunk_data: bytes,
        *,
        room_id: int,
    ) -> RecordingChunk:
        """Store one ordered chunk while reserving room and owner quotas atomically."""
        if seq < 0:
            raise RecordingError("شمارهٔ تکه نامعتبر است.")
        if not chunk_data:
            raise RecordingError("تکهٔ ارسالی خالی است.")
        if len(chunk_data) > self.settings.max_recording_chunk_bytes:
            raise QuotaExceededError("اندازهٔ تکه از سقف مجاز آپلود ضبط بیشتر است.")
        if len(chunk_data) > self.settings.max_recording_bytes:
            raise QuotaExceededError("اندازهٔ تکهٔ ضبط غیرمجاز است.")

        # Use one lock order everywhere (room -> recording -> owner) so parallel
        # chunks, finalization and speaker deletion cannot deadlock on PostgreSQL.
        room = self._lock_room(session, room_id)
        rec = session.execute(
            select(RecordingSession)
            .where(RecordingSession.id == session_id, RecordingSession.room_id == room_id)
            .with_for_update()
        ).scalar_one_or_none()
        if not rec:
            raise NotFoundError("نشست ضبط متعلق به این اتاق یافت نشد.")
        if rec.status not in self.ACTIVE_STATUSES:
            raise RecordingError(f"امکان ارسال تکه برای ضبط در وضعیت {rec.status} وجود ندارد.")

        existing = session.execute(
            select(RecordingChunk).where(
                RecordingChunk.session_id == rec.id,
                RecordingChunk.seq == seq,
            )
        ).scalar_one_or_none()
        if existing:
            return existing
        if seq != rec.chunk_seq:
            raise RecordingError(f"ترتیب تکه‌ها نامعتبر است؛ تکهٔ بعدی باید {rec.chunk_seq} باشد.")
        if rec.chunk_seq >= self.settings.recording_max_chunks:
            raise RecordingError("حداکثر تعداد تکه‌های مجاز برای این ضبط پر شده است.")
        if rec.bytes_received + len(chunk_data) > self.settings.max_recording_bytes:
            raise QuotaExceededError("حجم کل ضبط از سقف مجاز سرور فراتر رفته است.")

        active_statuses = ("recording", "paused", "finalizing")
        room_reserved = session.execute(
            select(func.coalesce(func.sum(RecordingSession.bytes_received), 0)).where(
                RecordingSession.room_id == room.id,
                RecordingSession.status.in_(active_statuses),
            )
        ).scalar_one()
        if room.storage_used_bytes + int(room_reserved) + len(chunk_data) > self.settings.max_room_storage_bytes:
            raise QuotaExceededError("سقف فضای اتاق برای دریافت این تکهٔ ضبط کافی نیست.")

        owner = session.execute(
            select(User)
            .where(User.id == room.owner_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if owner:
            owner_reserved = session.execute(
                select(func.coalesce(func.sum(RecordingSession.bytes_received), 0))
                .join(Room, Room.id == RecordingSession.room_id)
                .where(
                    Room.owner_id == owner.id,
                    RecordingSession.status.in_(active_statuses),
                )
            ).scalar_one()
            if owner.storage_used_bytes + int(owner_reserved) + len(chunk_data) > self.settings.max_user_storage_bytes:
                raise QuotaExceededError("سقف کل فضای حساب برای دریافت این تکهٔ ضبط کافی نیست.")

        available = self.storage.available_bytes()
        if available is not None and len(chunk_data) > max(0, available - 8 * 1024 * 1024):
            raise QuotaExceededError("فضای خالی دیسک برای دریافت این تکهٔ ضبط کافی نیست.")

        chunk_key = f"chunks/{rec.room_id}/{rec.id}/{seq:08d}.bin"
        size_bytes, _ = await self.storage.save_bytes(chunk_key, chunk_data)
        try:
            chunk = RecordingChunk(
                session_id=rec.id,
                seq=seq,
                storage_key=chunk_key,
                backend=self.settings.storage_backend,
                size_bytes=size_bytes,
                created_at_ms=utc_now_ms(),
            )
            session.add(chunk)
            rec.chunk_seq = seq + 1
            rec.bytes_received += size_bytes
            rec.last_chunk_at_ms = utc_now_ms()
            rec.version += 1
            session.flush()
            return chunk
        except Exception:
            await self.storage.delete(chunk_key)
            raise

    @staticmethod
    def _extension_for_mime(mime_type: str) -> str:
        mime = (mime_type or "").split(";", 1)[0].strip().lower()
        return {
            "audio/webm": ".webm",
            "audio/ogg": ".ogg",
            "audio/mp4": ".m4a",
            "audio/mpeg": ".mp3",
            "audio/wav": ".wav",
            "audio/x-wav": ".wav",
        }.get(mime, ".webm")

    @staticmethod
    def _local_date_string(room: Room, now_ms: int) -> str:
        tz_name = room.owner.timezone if room.owner and room.owner.timezone else "UTC"
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo("UTC")
        when = dt.datetime.fromtimestamp(now_ms / 1000, tz=dt.UTC).astimezone(tz)
        return when.strftime("%Y%m%d_%H%M%S")

    async def finish_and_save(
        self,
        session: Session,
        rec_session: RecordingSession,
    ) -> SpeechFile | None:
        """Finalize one recording exactly once and keep retryable failures recoverable."""
        room = self._lock_room(session, rec_session.room_id)
        rec = session.execute(
            select(RecordingSession)
            .where(RecordingSession.id == rec_session.id, RecordingSession.room_id == room.id)
            .with_for_update()
        ).scalar_one_or_none()
        if not rec:
            raise NotFoundError("نشست ضبط یافت نشد.")
        if rec.status in ("saved", "discarded"):
            return rec.final_file
        if rec.status == "finalizing":
            raise ConflictError(
                "این ضبط هم‌زمان در حال ذخیره‌سازی است.",
                code="RECORDING_FINALIZING",
            )
        if rec.status not in self.ACTIVE_STATUSES:
            raise RecordingError(
                f"امکان نهایی‌سازی ضبط در وضعیت {rec.status} وجود ندارد."
            )

        now_ms = utc_now_ms()
        if rec.status == "recording" and rec.active_since_ms > 0:
            rec.recorded_ms += max(0, now_ms - rec.active_since_ms)
            rec.active_since_ms = 0
        rec.recorded_ms = min(rec.recorded_ms, self.settings.max_recording_seconds * 1000)

        chunks = session.execute(
            select(RecordingChunk)
            .where(RecordingChunk.session_id == rec.id)
            .order_by(RecordingChunk.seq.asc())
        ).scalars().all()
        if not chunks:
            rec.status = "discarded"
            rec.ended_at_ms = now_ms
            rec.active_since_ms = 0
            rec.version += 1
            session.flush()
            return None

        actual_sequences = [c.seq for c in chunks]
        if actual_sequences != list(range(len(chunks))) or rec.chunk_seq != len(chunks):
            rec.status = "failed"
            rec.error = "دادهٔ ضبط ناقص یا نامرتب است."
            rec.ended_at_ms = now_ms
            rec.active_since_ms = 0
            rec.version += 1
            session.flush()
            raise RecordingError("ترتیب یا تعداد تکه‌های ضبط کامل نیست؛ فایل ذخیره نشد.")

        owner = session.execute(
            select(User)
            .where(User.id == room.owner_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        total_expected = sum(c.size_bytes for c in chunks)
        if total_expected != rec.bytes_received:
            rec.status = "failed"
            rec.error = "حجم ثبت‌شده با مجموع تکه‌های ضبط یکسان نیست."
            rec.ended_at_ms = now_ms
            rec.version += 1
            session.flush()
            raise RecordingError("اطلاعات ضبط ناسازگار است؛ فایل ذخیره نشد.")

        active_statuses = self.BLOCKING_STATUSES
        room_reserved_bytes = session.execute(
            select(func.coalesce(func.sum(RecordingSession.bytes_received), 0)).where(
                RecordingSession.room_id == room.id,
                RecordingSession.id != rec.id,
                RecordingSession.status.in_(active_statuses),
            )
        ).scalar_one()
        if (
            room.storage_used_bytes + int(room_reserved_bytes) + total_expected
            > self.settings.max_room_storage_bytes
        ):
            rec.status = "paused"
            rec.error = "سقف فضای اتاق برای ذخیرهٔ ضبط و نشست‌های دیگر کافی نیست."
            rec.version += 1
            session.flush()
            raise QuotaExceededError("فضای اتاق با احتساب ضبط‌های دیگر برای ذخیرهٔ این فایل کافی نیست.")

        owner_reserved_bytes = 0
        if owner:
            owner_reserved_bytes = session.execute(
                select(func.coalesce(func.sum(RecordingSession.bytes_received), 0))
                .join(Room, Room.id == RecordingSession.room_id)
                .where(
                    Room.owner_id == owner.id,
                    RecordingSession.id != rec.id,
                    RecordingSession.status.in_(active_statuses),
                )
            ).scalar_one()
        if (
            owner
            and owner.storage_used_bytes + int(owner_reserved_bytes) + total_expected
            > self.settings.max_user_storage_bytes
        ):
            rec.status = "paused"
            rec.error = "سقف فضای حساب با احتساب ضبط‌های دیگر برای ذخیره کافی نیست."
            rec.version += 1
            session.flush()
            raise QuotaExceededError(
                "سقف فضای حساب با احتساب فایل‌های ذخیره‌شده و ضبط‌های در حال دریافت کافی نیست."
            )

        available = self.storage.available_bytes()
        if available is not None and total_expected + 64 * 1024 * 1024 > available:
            rec.status = "paused"
            rec.error = "فضای خالی دیسک برای ساخت فایل نهایی کافی نیست."
            rec.version += 1
            session.flush()
            raise QuotaExceededError("فضای خالی دیسک برای ذخیرهٔ ضبط کافی نیست.")

        speaker_name = rec.speaker_name or "بدون نام"
        date_str = self._local_date_string(room, now_ms)
        ext = self._extension_for_mime(rec.mime_type)
        display_filename = (
            f"{sanitize_filename(room.name, fallback='اتاق')} - "
            f"{sanitize_filename(speaker_name, fallback='سخنران')} - {date_str}{ext}"
        )[:255]
        safe_display = sanitize_filename(display_filename, fallback="recording")
        target_key = f"recordings/{room.id}/{rec.id}_{safe_display}"
        chunk_keys = [c.storage_key for c in chunks]

        rec.status = "finalizing"
        rec.version += 1
        session.flush()

        try:
            total_size, sha256_hash = await self.storage.assemble_chunks(target_key, chunk_keys)
            if total_size != total_expected:
                raise RecordingError("حجم فایل نهایی با مجموع تکه‌های ضبط یکسان نیست.")
            speech_file = SpeechFile(
                room_id=room.id,
                speaker_id=rec.speaker_id,
                filename=display_filename,
                storage_key=target_key,
                backend=self.settings.storage_backend,
                content_type=(rec.mime_type or "audio/webm").split(";", 1)[0],
                size_bytes=total_size,
                upload_type="recording",
                duration_ms=rec.recorded_ms,
                speaker_name=speaker_name[:120],
                sha256=sha256_hash,
                created_at_ms=now_ms,
                updated_at_ms=now_ms,
            )
            session.add(speech_file)
            session.flush()
        except Exception as exc:
            try:
                await self.storage.delete(target_key)
            except Exception:
                enqueue_cleanup(
                    session,
                    backend=self.settings.storage_backend,
                    storage_key=target_key,
                    reason="recording_assembly_failed",
                )
            rec.status = "paused"
            rec.error = str(exc)[:255]
            rec.active_since_ms = 0
            rec.ended_at_ms = 0
            rec.version += 1
            session.flush()
            if isinstance(exc, RecordingError):
                raise
            raise RecordingError("مونتاژ و ذخیرهٔ فایل ضبط ناموفق بود؛ ضبط برای تلاش مجدد نگه داشته شد.") from exc

        rec.status = "saved"
        rec.ended_at_ms = now_ms
        rec.active_since_ms = 0
        rec.final_file_id = speech_file.id
        rec.error = ""
        rec.version += 1
        room.storage_used_bytes += total_size
        if owner:
            owner.storage_used_bytes += total_size

        for c in chunks:
            enqueue_cleanup(
                session,
                backend=c.backend,
                storage_key=c.storage_key,
                reason="chunk_assembled",
            )
        session.flush()
        return speech_file

    def discard_recording_sync(
        self,
        session: Session,
        rec_session: RecordingSession,
    ) -> None:
        rec = session.execute(
            select(RecordingSession)
            .where(RecordingSession.id == rec_session.id)
            .with_for_update()
        ).scalar_one_or_none()
        if not rec or rec.status in ("saved", "discarded"):
            return
        for c in rec.chunks:
            enqueue_cleanup(
                session,
                backend=c.backend,
                storage_key=c.storage_key,
                reason="recording_discarded",
            )
        rec.status = "discarded"
        rec.ended_at_ms = utc_now_ms()
        rec.active_since_ms = 0
        rec.error = ""
        rec.version += 1
        session.flush()
