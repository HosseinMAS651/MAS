"""سرویس پاک‌سازی پس‌زمینهٔ فایل‌ها و آزادسازی منابع."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..core.timeutil import utc_now_ms
from ..db.models import CleanupQueue, RecordingSession
from ..storage.base import StorageBackend

logger = logging.getLogger("mas.cleanup")


class CleanupService:
    def __init__(self, settings: Settings, storage: StorageBackend) -> None:
        self.settings = settings
        self.storage = storage

    async def process_queue(self, session: Session, *, limit: int = 50) -> int:
        """پردازش صف حذف فایل‌ها و پاک‌سازی قطعی از سیستم ذخیره‌سازی."""
        now_ms = utc_now_ms()
        items = session.execute(
            select(CleanupQueue)
            .where(CleanupQueue.next_attempt_at_ms <= now_ms)
            .order_by(CleanupQueue.id.asc())
            .limit(limit)
        ).scalars().all()

        deleted_count = 0
        for item in items:
            try:
                await self.storage.delete(item.storage_key)
                session.delete(item)
                deleted_count += 1
            except Exception as exc:
                item.attempts += 1
                item.last_error = str(exc)[:250]
                # بازه تاخیر تصاعدی (Backoff)
                delay_sec = min(3600, (2 ** item.attempts) * 10)
                item.next_attempt_at_ms = now_ms + (delay_sec * 1000)
                logger.warning("خطا در حذف فایل %s: %s", item.storage_key, exc)

        session.flush()
        return deleted_count

    async def clean_abandoned_recordings(self, session: Session) -> int:
        """پاک‌سازی خودکار نشست‌های ضبط رها شده توسط کاربران."""
        abandon_ms = self.settings.recording_abandon_seconds * 1000
        threshold_ms = utc_now_ms() - abandon_ms

        abandoned = session.execute(
            select(RecordingSession).where(
                RecordingSession.status.in_(["recording", "paused"]),
                RecordingSession.last_chunk_at_ms < threshold_ms,
            )
        ).scalars().all()

        count = 0
        for rec in abandoned:
            for c in rec.chunks:
                session.add(
                    CleanupQueue(
                        backend=c.backend,
                        storage_key=c.storage_key,
                        reason="abandoned_recording",
                    )
                )
            rec.status = "discarded"
            rec.error = "به دلیل قطع ارتباط و عدم دریافت داده جدید متوقف شد."
            count += 1

        session.flush()
        return count
