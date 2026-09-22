"""امنیت: هش رمز عبور (Argon2id + پشتیبانی از PBKDF2 قدیمی)، استخراج امن IP،
توکن‌های ضد CSRF، و نرمال‌سازی متن.

باگ‌های برطرف‌شده در این ماژول:
- **C-02**: مقایسهٔ رمز عبور غیر ASCII (رفع TypeError ناشی از hmac.compare_digest).
- **BE-01/BE-01b**: استخراج امن IP از X-Forwarded-For با توجه به تعداد پرش‌های پروکسی مجاز.
- **BE-20/BE-25**: نرمال‌سازی نویسه‌های فارسی/عربی و جلوگیری از جعل حساب کاربری با حروف بزرگ/کوچک.
- مهاجرت خودکار و بی‌صدا از هش‌های PBKDF2 نسخهٔ قدیم به Argon2id بدون از دست رفتن دسترسی کاربر.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import unicodedata

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from ..config import Settings

_PBKDF2_PREFIX = "pbkdf2_sha256"


class SecurityManager:
    """مدیریت رمزنگاری، هش‌ها و توکن‌ها با دسترسی به تنظیمات برنامه."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._hasher = PasswordHasher(
            time_cost=settings.argon2_time_cost,
            memory_cost=settings.argon2_memory_cost_kib,
            parallelism=settings.argon2_parallelism,
            hash_len=32,
            salt_len=16,
        )

    # ── رمز عبور ─────────────────────────────────────────────
    def hash_password(self, password: str) -> str:
        """هش رمز عبور با Argon2id."""
        return self._hasher.hash(password)

    def verify_password(self, password: str, encoded_hash: str) -> tuple[bool, bool]:
        """اعتبارسنجی رمز عبور.

        خروجی:
            (آیا رمز صحیح است؟ , آیا هش نیاز به ارتقا به Argon2id دارد؟)
        """
        if not encoded_hash or not password:
            return False, False

        # حالت اول: هش نسخهٔ قدیم PBKDF2
        if encoded_hash.startswith(_PBKDF2_PREFIX):
            valid = self._verify_pbkdf2(password, encoded_hash)
            # اگر رمز درست بود، بلافاصله باید به Argon2id ارتقا پیدا کند
            return valid, valid

        # حالت دوم: Argon2id
        try:
            self._hasher.verify(encoded_hash, password)
            needs_rehash = self._hasher.check_needs_rehash(encoded_hash)
            return True, needs_rehash
        except VerifyMismatchError:
            return False, False
        except Exception:
            return False, False

    def _verify_pbkdf2(self, password: str, encoded: str) -> bool:
        """بررسی هش‌های قدیمی pbkdf2_sha256$310000$salt$digest برای حفظ حساب‌های قبلی."""
        try:
            parts = encoded.split("$")
            if len(parts) != 4 or parts[0] != _PBKDF2_PREFIX:
                return False
            rounds = int(parts[1])
            salt = bytes.fromhex(parts[2])
            expected_digest = parts[3]
            candidate = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), salt, rounds
            ).hex()
            return secrets.compare_digest(candidate, expected_digest)
        except Exception:
            return False

    # ── توکن‌ها ──────────────────────────────────────────────
    def generate_session_token(self) -> str:
        """ساخت توکن خام نشست کاربر (ارسال در کوکی)."""
        return secrets.token_urlsafe(32)

    def hash_token(self, token: str) -> str:
        """هش HMAC توکن برای ذخیره‌سازی در دیتابیس (حتی اگر DB نشت کند توکن افشا نمی‌شود)."""
        return hmac.new(
            self.settings.secret_key.encode("utf-8"),
            token.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def generate_csrf_token(self) -> str:
        """ساخت توکن CSRF تصادفی."""
        return secrets.token_urlsafe(32)

    def verify_csrf(self, raw_token: str, expected_hash: str) -> bool:
        """اعتبارسنجی توکن CSRF در برابر هش ذخیره‌شده."""
        if not raw_token or not expected_hash:
            return False
        candidate = self.hash_token(raw_token)
        return secrets.compare_digest(candidate, expected_hash)

    def generate_public_token(self) -> str:
        """ساخت توکن تصادفی ۴۳ کاراکتری برای لینک عمومی اتاق."""
        return secrets.token_urlsafe(32)

    # ── استخراج IP کلاینت (رفع BE-01/BE-01b) ─────────────────
    def extract_client_ip(self, request_headers: dict[str, str], peer_ip: str | None) -> str:
        """استخراج امن IP واقعی کلاینت بر اساس تعداد پرش‌های پروکسی مجاز.

        تنظیمات ``MAS_TRUSTED_PROXY_HOPS`` مشخص می‌کند چند پروکسی معتبر جلوی برنامه هستند
        (مثلاً در Render برابر 1 است). IPهای قبل از آن را به عنوان کلاینت می‌پذیریم.
        اگر hops برابر 0 باشد، هدرهای XFF کاملاً نادیده گرفته می‌شوند.
        """
        peer = (peer_ip or "").strip()
        hops = self.settings.trusted_proxy_hops
        if hops <= 0:
            return peer or "127.0.0.1"

        xff = request_headers.get("x-forwarded-for") or request_headers.get("X-Forwarded-For")
        if not xff:
            return peer or "127.0.0.1"

        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if not parts:
            return peer or "127.0.0.1"

        # انتخاب آی‌پیِ پشت تعداد پرش‌های معتبر
        if len(parts) >= hops:
            candidate = parts[-hops]
        else:
            candidate = parts[0]

        # اعتبارسنجی ساختار IP برای جلوگیری از تزریق رشته‌های نامعتبر
        clean = re.sub(r"[^0-9a-fA-F:.]", "", candidate)
        return clean or peer or "127.0.0.1"


# ── ابزارهای نرمال‌سازی متن ──────────────────────────────────
_ARABIC_TO_PERSIAN = {
    ord("ي"): "ی",
    ord("ى"): "ی",
    ord("ك"): "ک",
    ord("ة"): "ه",
    ord("ۀ"): "ه",
    ord("۰"): "0",
    ord("۱"): "1",
    ord("۲"): "2",
    ord("۳"): "3",
    ord("۴"): "4",
    ord("۵"): "5",
    ord("۶"): "6",
    ord("۷"): "7",
    ord("۸"): "8",
    ord("۹"): "9",
    ord("٠"): "0",
    ord("١"): "1",
    ord("٢"): "2",
    ord("٣"): "3",
    ord("٤"): "4",
    ord("٥"): "5",
    ord("٦"): "6",
    ord("٧"): "7",
    ord("٨"): "8",
    ord("٩"): "9",
}


def normalize_persian_text(text: str) -> str:
    """یکسان‌سازی حروف و ارقام عربی/فارسی و حذف نویسه‌های کنترلی."""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFC", text)
    translated = normalized.translate(_ARABIC_TO_PERSIAN)
    # حذف کاراکترهای کنترلی خطرناک به‌جز فاصله و خط جدید
    cleaned = "".join(c for c in translated if c in "\n\r\t " or unicodedata.category(c)[0] != "C")
    return cleaned.strip()


def normalize_username(raw: str) -> str:
    """نرمال‌سازی نام کاربری برای نمایش (فاصله‌های اضافی حذف می‌شود)."""
    clean = normalize_persian_text(raw or "")
    return re.sub(r"\s+", " ", clean)


def username_to_key(username: str) -> str:
    """تبدیل نام کاربری به کلید جست‌وجو و یکتایی (حساس نبودن به بزرگی/کوچکی و کاراکترهای معادل)."""
    clean = normalize_persian_text(username or "")
    return clean.casefold().replace(" ", "").replace("_", "").replace("-", "")


def sanitize_filename(name: str, *, fallback: str = "file") -> str:
    """پاک‌سازی نام فایل برای نمایش امن (حفظ حروف فارسی، حذف کاراکترهای خطرناک مسیر)."""
    if not name:
        return fallback
    clean = normalize_persian_text(name)
    # حذف کاراکترهای مسیر و علائم خاص خطرناک
    safe = re.sub(r'[\\/*?:"<>|\x00-\x1f]', "", clean)
    # حذف نقطه‌های متوالی برای جلوگیری از path traversal
    safe = re.sub(r"\.{2,}", ".", safe)
    safe = safe.strip(" .")
    return safe[:180] or fallback
