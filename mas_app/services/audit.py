"""سرویس ثبت لاگ‌های ممیزی و امنیتی (رفع SEC-10)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from ..core.timeutil import utc_now_ms
from ..db.models import AuditLog


def log_event(
    session: Session,
    *,
    action: str,
    actor_user_id: int | None = None,
    actor_username: str = "",
    severity: str = "info",
    target_type: str = "",
    target_id: str = "",
    detail: dict[str, Any] | str = "",
    ip: str = "",
    user_agent: str = "",
) -> AuditLog:
    """ثبت یک رویداد امنیتی یا عملیاتی در دیتابیس."""
    detail_str = detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)
    entry = AuditLog(
        actor_user_id=actor_user_id,
        actor_username=actor_username[:32],
        action=action[:48],
        severity=severity if severity in {"info", "warning", "error", "security"} else "info",
        target_type=target_type[:32],
        target_id=str(target_id)[:64],
        detail=detail_str,
        ip=ip[:64],
        user_agent=user_agent[:255],
        created_at_ms=utc_now_ms(),
    )
    session.add(entry)
    return entry
