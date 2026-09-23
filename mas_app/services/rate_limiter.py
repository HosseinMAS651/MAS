"""Atomic DB-backed rate limiter."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.errors import RateLimitExceededError
from ..core.timeutil import utc_now_ms
from ..db.models import RateLimitBucket


class RateLimiter:
    @staticmethod
    def check_and_increment(
        session: Session,
        bucket_key: str,
        *,
        action: str,
        max_attempts: int,
        window_seconds: int,
    ) -> None:
        now = utc_now_ms()
        window_ms = window_seconds * 1000

        bucket = session.execute(
            select(RateLimitBucket)
            .where(RateLimitBucket.bucket_key == bucket_key)
            .with_for_update()
        ).scalar_one_or_none()

        if bucket is None:
            try:
                with session.begin_nested():
                    bucket = RateLimitBucket(
                        bucket_key=bucket_key,
                        action=action,
                        count=1,
                        window_started_at_ms=now,
                        blocked_until_ms=0,
                    )
                    session.add(bucket)
                    session.flush()
                return
            except IntegrityError:
                bucket = session.execute(
                    select(RateLimitBucket)
                    .where(RateLimitBucket.bucket_key == bucket_key)
                    .with_for_update()
                ).scalar_one_or_none()
                if bucket is None:
                    raise

        if bucket.blocked_until_ms > now:
            retry_after = max(1, (bucket.blocked_until_ms - now + 999) // 1000)
            raise RateLimitExceededError(retry_after_seconds=retry_after)

        if now - bucket.window_started_at_ms >= window_ms:
            bucket.window_started_at_ms = now
            bucket.count = 1
            bucket.blocked_until_ms = 0
            bucket.action = action
            session.flush()
            return

        if bucket.count >= max_attempts:
            bucket.blocked_until_ms = bucket.window_started_at_ms + window_ms
            session.flush()
            retry_after = max(1, (bucket.blocked_until_ms - now + 999) // 1000)
            raise RateLimitExceededError(retry_after_seconds=retry_after)

        bucket.count += 1
        bucket.action = action
        session.flush()

    @staticmethod
    def reset(session: Session, bucket_key: str) -> None:
        bucket = session.execute(
            select(RateLimitBucket).where(RateLimitBucket.bucket_key == bucket_key).with_for_update()
        ).scalar_one_or_none()
        if bucket:
            session.delete(bucket)
            session.flush()
