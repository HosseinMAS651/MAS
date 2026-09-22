"""سیستم استاندارد خطاهای برنامه با پیام‌های فارسی و کدهای خطای ماشین‌خوان.

همهٔ پاسخ‌های خطای API از قالب استاندارد زیر پیروی می‌کنند:

.. code-block:: json

    {
        "ok": false,
        "error": {
            "code": "ROOM_NOT_FOUND",
            "message": "اتاق مورد نظر یافت نشد.",
            "details": {}
        }
    }

این کار باگ‌های BE-07، BE-08، BE-09 و گزارش audit را که پاسخ‌های انگلیسی خام یا ۵۰۰
برمی‌گرداندند ریشه‌ای حل می‌کند.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """پایهٔ همهٔ خطاهای کنترل‌شدهٔ دامنه."""

    status_code: int = 400
    code: str = "BAD_REQUEST"
    message: str = "درخواست نامعتبر است."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message or self.message)
        if message is not None:
            self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.details: dict[str, Any] = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": false,
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            },
        }


# پایتون boolean
false = False
true = True


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"
    message = "موردی با این مشخصات یافت نشد."


class UnauthorizedError(AppError):
    status_code = 401
    code = "UNAUTHORIZED"
    message = "لطفاً ابتدا وارد حساب کاربری خود شوید."


class ForbiddenError(AppError):
    status_code = 403
    code = "FORBIDDEN"
    message = "شما اجازهٔ دسترسی به این بخش را ندارید."


class ConflictError(AppError):
    status_code = 409
    code = "CONFLICT"
    message = "تداخل در داده‌ها رخ داده است؛ لطفاً صفحه را تازه‌سازی کنید."


class QuotaExceededError(AppError):
    status_code = 413
    code = "QUOTA_EXCEEDED"
    message = "سقف مجاز منبع (تعداد اتاق، ظرفیت یا فضای دیسک) پر شده است."


class RateLimitExceededError(AppError):
    status_code = 429
    code = "RATE_LIMITED"
    message = "تعداد درخواست‌های شما بیش از حد مجاز است؛ لطفاً کمی بعد دوباره تلاش کنید."

    def __init__(
        self,
        message: str | None = None,
        *,
        retry_after_seconds: int = 60,
        details: dict[str, Any] | None = None,
    ) -> None:
        merged = {"retry_after_seconds": retry_after_seconds, **(details or {})}
        super().__init__(message, code="RATE_LIMITED", details=merged, status_code=429)
        self.retry_after_seconds = retry_after_seconds


class ValidationAppError(AppError):
    status_code = 400
    code = "VALIDATION_ERROR"
    message = "اطلاعات ارسالی نامعتبر است."


class FileUploadError(AppError):
    status_code = 400
    code = "FILE_UPLOAD_ERROR"
    message = "خطا در پردازش فایل ارسالی."


class RecordingError(AppError):
    status_code = 400
    code = "RECORDING_ERROR"
    message = "عملیات ضبط با خطا مواجه شد."


class InternalServerError(AppError):
    status_code = 500
    code = "INTERNAL_SERVER_ERROR"
    message = "خطای غیرمنتظره در سرور رخ داده است. لطفاً بعداً تلاش کنید."
