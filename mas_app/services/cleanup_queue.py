"""Idempotent cleanup-queue helpers."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db.models import CleanupQueue


def enqueue_cleanup(session: Session, *, backend: str, storage_key: str, reason: str) -> CleanupQueue:
    """Queue a physical object for deletion once.

    The database has a unique constraint on (backend, storage_key), so every
    call is idempotent and safe when multiple workflows discover the same
    orphan concurrently.
    """
    existing = session.execute(
        select(CleanupQueue).where(
            CleanupQueue.backend == backend,
            CleanupQueue.storage_key == storage_key,
        )
    ).scalar_one_or_none()
    if existing is not None:
        if not existing.reason:
            existing.reason = reason[:32]
        return existing
    item = CleanupQueue(
        backend=backend,
        storage_key=storage_key,
        reason=reason[:32],
    )
    try:
        # Savepoint prevents a duplicate-key race from poisoning the caller transaction.
        with session.begin_nested():
            session.add(item)
            session.flush()
        return item
    except IntegrityError:
        existing = session.execute(
            select(CleanupQueue).where(
                CleanupQueue.backend == backend,
                CleanupQueue.storage_key == storage_key,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        raise
