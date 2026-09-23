"""Reusable input validation helpers."""
from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import ValidationAppError


def validate_timezone(value: str) -> str:
    clean = (value or "").strip()
    try:
        ZoneInfo(clean)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValidationAppError("منطقهٔ زمانی نامعتبر است.") from exc
    return clean
