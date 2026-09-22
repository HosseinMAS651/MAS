"""ابزارهای زمان.

همهٔ زمان‌ها به‌صورت **epoch میلی‌ثانیهٔ UTC** ذخیره می‌شوند (BigInt) تا:

* مشکل ``default=0`` و نمایش «1970-01-01» در UI از بین برود (باگ DB-07 گزارش audit)،
* تبدیل به منطقهٔ زمانی/تقویم انتخابی کاربر در سمت کلاینت انجام شود (بدون وابستگی
  جدید در سرور و بدون نمایش زمان اشتباه — باگ DB-08)،
* دقت میلی‌ثانیه برای تایمر سخنرانی کافی باشد.

دربارهٔ پرش ساعت سرور (باگ DB-10): همهٔ محاسبه‌های تایمر با
:func:`non_negative_delta` انجام می‌شوند، بنابراین اگر ساعت سرور به عقب برگردد
(تنظیم NTP)، تایمر به عقب پرش نمی‌کند و منفی نمی‌شود؛ فقط برای همان بازه متوقف
می‌ماند. زمان‌های پایدارشده همیشه epoch واقعی هستند (بدون پایهٔ زمانی دوم)، پس
پس از restart هم مقدارها معنا دارند.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime


def utc_now_ms() -> int:
    """زمان فعلی UTC به میلی‌ثانیه."""
    return int(time.time() * 1000)


def utc_now_seconds() -> int:
    """زمان فعلی UTC به ثانیه."""
    return int(time.time())


def non_negative_delta(started_at_ms: int | None, now_ms: int | None = None, *, cap_ms: int | None = None) -> int:
    """مدت زمان سپری‌شده از ``started_at_ms``، همیشه >= 0 و (اختیاریاً) دارای سقف.

    اگر ساعت سرور به عقب برگردد، نتیجه صفر می‌شود (تایمر عقب نمی‌رود).
    """
    if not started_at_ms:
        return 0
    current = utc_now_ms() if now_ms is None else now_ms
    delta = current - int(started_at_ms)
    if delta <= 0:
        return 0
    if cap_ms is not None:
        delta = min(delta, int(cap_ms))
    return delta


def ms_to_iso(value: int | None) -> str | None:
    """تبدیل epoch میلی‌ثانیه به ISO-8601 UTC (برای پاسخ API و مصرف کلاینت)."""
    if not value:
        return None
    moment = datetime.fromtimestamp(value / 1000, tz=UTC).replace(microsecond=0)
    return moment.isoformat().replace("+00:00", "Z")


def iso_to_ms(value: str | None) -> int | None:
    """تبدیل ISO-8601 به epoch میلی‌ثانیه (بدون استثنا؛ در صورت نامعتبر بودن None)."""
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp() * 1000)


def parse_int(value: object) -> int | None:
    """تبدیل امن هر ورودی به عدد صحیح؛ اگر ممکن نبود ``None`` (هرگز استثنا نمی‌دهد).

    رشتهٔ خالی، ``None``، بولین و متن‌های غیرعددی همه ``None`` می‌شوند تا لایهٔ
    اعتبارسنجی بتواند به‌جای ۵۰۰ (باگ‌های C-03/BE-12 در گزارش audit) خطای ۴۰۰ با
    پیام فارسی برگرداند. ارقام فارسی/عربی هم پذیرفته می‌شوند چون ``int()`` آن‌ها
    را می‌فهمد (رفتار عمدی برای فرم‌های فارسی).
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return None if value != value else int(value)  # NaN → None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def bound_int(value: object, *, minimum: int, maximum: int, default: int | None = None) -> int:
    """تبدیل ورودی و محدودکردن آن به بازهٔ ``[minimum, maximum]``.

    اگر ورودی غیرعددی باشد: در صورت ارائهٔ ``default`` همان برگردانده می‌شود وگرنه
    ``ValueError`` (که لایهٔ API آن را به خطای ۴۰۰ با پیام فارسی تبدیل می‌کند).
    مقادیر عددی خارج از بازه به لبهٔ بازه محدود می‌شوند.
    """
    number = parse_int(value)
    if number is None:
        if default is not None:
            return max(minimum, min(maximum, default))
        raise ValueError(f"مقدار عددی نامعتبر: {value!r}")
    # محافظت در برابر سرریز در درایور دیتابیس (باگ BE-12: OverflowError → ۵۰۰)
    number = max(-9_223_372_036_854_775_808, min(9_223_372_036_854_775_807, number))
    return max(minimum, min(maximum, number))
