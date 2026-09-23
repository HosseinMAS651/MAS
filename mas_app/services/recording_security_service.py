"""Secure RecordingService drop-in: binds every chunk to its room and enforces sequence."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.errors import NotFoundError, RecordingError
from ..core.timeutil import utc_now_ms
from ..db.models import RecordingChunk, RecordingSession
from .recording_service import RecordingService as BaseRecordingService


class SecureRecordingService(BaseRecordingService):
    async def save_chunk(
        self,
        session: Session,
        session_id: int,
        seq: int,
        chunk_data: bytes,
        *,
        room_id: int,
    ) -> RecordingChunk:
        if seq < 0:
            raise RecordingError("شمارهٔ تکه نامعتبر است.")
        if not chunk_data:
            raise RecordingError("تکهٔ ارسالی خالی است.")

        rec = session.execute(
            select(RecordingSession).where(
                RecordingSession.id == session_id,
                RecordingSession.room_id == room_id,
            )
        ).scalar_one_or_none()
        if not rec:
            raise NotFoundError("نشست ضبط متعلق به این اتاق یافت نشد.")
        if rec.status not in ["recording", "paused"]:
            raise RecordingError(f"امکان ارسال تکه برای ضبط در وضعیت {rec.status} وجود ندارد.")

        expected = rec.chunk_seq
        if seq != expected:
            # Retries are safe only when the exact sequence already exists.
            existing = session.execute(
                select(RecordingChunk).where(
                    RecordingChunk.session_id == rec.id,
                    RecordingChunk.seq == seq,
                )
            ).scalar_one_or_none()
            if existing:
                return existing
            raise RecordingError(f"ترتیب تکه‌ها نامعتبر است؛ تکهٔ بعدی باید {expected} باشد.")

        if rec.chunk_seq >= self.settings.recording_max_chunks:
            raise RecordingError("حداکثر تعداد تکه‌های مجاز برای این ضبط پر شده است.")
        if (rec.bytes_received + len(chunk_data)) > self.settings.max_recording_bytes:
            raise RecordingError("حجم کل ضبط از سقف مجاز سرور فراتر رفته است.")

        chunk_key = f"chunks/{rec.room_id}/{rec.id}_{seq:06d}.bin"
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
            session.flush()
            return chunk
        except Exception:
            await self.storage.delete(chunk_key)
            raise
