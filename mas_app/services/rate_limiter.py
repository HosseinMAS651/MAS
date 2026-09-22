"""محدودسازی نرخ پایدار در دیتابیس (رفع BE-01, BE-02, SEC-01)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.errors import RateLimitExceededError
from ..core.timeutil import utc_now_ms
from ..db.models import RateLimitBucket


class RateLimiter:
    """محدودکنندهٔ درخواست‌ها بر اساس کلید پایدار در دیتابیس."""

    @staticmethod
    def check_and_increment(
        session: Session,
        bucket_key: str,
        *,
        action: str,
        max_attempts: int,
        window_seconds: int,
        block_seconds: int = 600,
    ) -> None:
        now_ms = utc_now_ms()
        window_ms = window_seconds * 1000
        block_ms = block_seconds * 1000

        bucket = session.execute(
            select(RateLimitBucket).where(RateLimitBucket.bucket_key == bucket_key)
        ).scalar_one_or_none()

        if bucket is None:
            bucket = RateLimitBucket(
                bucket_key=bucket_key,
                action=action,
                count=1,
                window_started_at_ms=now_ms,
                blocked_until_ms=0,
            )
            session.add(bucket)
            session.flush()
            return

        # بررسی بلاک بودن
        if bucket.blocked_until_ms > now_ms:
            remaining_sec = max(1, (bucket.blocked_until_ms - now_ms) // 1000)
            raise RateLimitExceededError(
                f"به دلیل تلاش‌های مکرر، دسترسی موقتاً مسدود شده است. لطفاً {remaining_sec} ثانیه دیگر دوباره تلاش کنید.",
                retry_after_seconds=remaining_sec,
            )

        # بررسی اتمام پنجره زمانی
        if (now_ms - bucket.window_started_at_ms) > window_ms:
            bucket.window_started_at_ms = now_ms
            bucket.count = 1
            bucket.blocked_until_ms = 0
            session.flush()
            return

        bucket.count += 1
        if bucket.count > max_attempts:
            bucket.blocked_until_ms = now_ms + block_ms
            session.flush()
            remaining_sec = block_seconds
            raise RateLimitExceededError(
                f"تعداد تلاش‌ها از حد مجاز فراتر رفت. حساب/آی‌پی شما به مدت {remaining_sec // 60} دقیقه مسدود شد.",
                retry_after_seconds=remaining_sec,
            )

        session.flush()

    @staticmethod
    def reset(session: Session, bucket_key: str) -> None:
        bucket = session.execute(
            select(RateLimitBucket).where(RateLimitBucket.bucket_key == bucket_key)
        ).scalar_one_or_none()
        if bucket:
            session.delete(bucket)
            session.flush()
