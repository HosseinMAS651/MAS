"""تنظیمات برنامه.

همهٔ تنظیمات از محیط (و اختیاریاً فایل ``.env``) خوانده می‌شوند و **در زمان
راه‌اندازی** اعتبارسنجی می‌شوند؛ اگر پیکربندی production ناامن یا ناقص باشد،
برنامه به‌جای اجرای بی‌صدا و از دست دادن داده، با پیام خطای روشن متوقف می‌شود.

این ماژول هیچ وضعیت سراسری (global state) ندارد: ``create_app(settings=...)``
نمونهٔ تنظیمات را می‌گیرد، بنابراین تست‌ها کاملاً ایزوله اجرا می‌شوند.
"""

from __future__ import annotations

import logging
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("mas.config")

BASE_DIR = Path(__file__).resolve().parent.parent

#: پسوندهای مجاز برای آپلود فایل سخنرانی (فایل‌های اجرایی/اسکریپت هرگز پذیرفته نمی‌شوند).
DEFAULT_ALLOWED_EXTENSIONS = (
    ".pdf,.doc,.docx,.odt,.txt,.md,.rtf,.ppt,.pptx,.odp,.xls,.xlsx,.ods,.csv,"
    ".png,.jpg,.jpeg,.gif,.webp,.svgz,.bmp,.tiff,"
    ".mp3,.m4a,.aac,.ogg,.oga,.opus,.wav,.flac,.weba,"
    ".mp4,.m4v,.webm,.ogv,.mov,.avi,.mkv"
)

#: نگاشت پسوند → نوع محتوای صوتی/تصویری که **ضبط** می‌شود.
#: ضبط مرورگر تقریباً همیشه audio/webm (کرومیوم) یا audio/mp4 (سافاری) است.
RECORDING_EXTENSIONS = {
    "audio/webm": ".weba",
    "audio/ogg": ".oga",
    "audio/mp4": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
}

Environment = Literal["development", "test", "production"]


class SettingsError(RuntimeError):
    """پیکربندی نامعتبر؛ برنامه باید با پیام روشن متوقف شود."""


class Settings(BaseSettings):
    """تنظیمات برنامه (همهٔ متغیرهای محیطی با پیشوند ``MAS_``)."""

    model_config = SettingsConfigDict(
        env_prefix="MAS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        validate_default=True,
    )

    # ── عمومی ────────────────────────────────────────────────
    env: Environment = "development"
    log_level: str = "INFO"
    public_base_url: str = ""
    enable_docs: bool | None = None

    # ── امنیت ────────────────────────────────────────────────
    secret_key: str = ""
    argon2_time_cost: int = Field(default=2, ge=1, le=16)
    argon2_memory_cost_kib: int = Field(default=19_456, ge=8_192, le=2_097_152)
    argon2_parallelism: int = Field(default=1, ge=1, le=16)

    # ── دیتابیس ──────────────────────────────────────────────
    database_url: str = Field(
        default="",
        validation_alias=AliasChoices("DATABASE_URL", "MAS_DATABASE_URL"),
    )
    allow_sqlite_in_production: bool = False
    db_echo: bool = False
    db_pool_size: int = Field(default=5, ge=1, le=200)
    db_max_overflow: int = Field(default=10, ge=0, le=200)
    db_pool_timeout_seconds: int = Field(default=30, ge=1, le=600)
    run_migrations_on_startup: bool = True

    # ── ذخیره‌سازی ───────────────────────────────────────────
    storage_backend: Literal["local", "s3"] = "local"
    storage_dir: str = "./uploads"
    s3_endpoint_url: str = ""
    s3_region: str = "us-east-1"
    s3_bucket: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_prefix: str = "mas/"
    s3_addressing_style: Literal["virtual", "path"] = "virtual"
    s3_use_presigned_download: bool = False
    s3_presigned_ttl_seconds: int = Field(default=900, ge=60, le=86_400)

    # ── سهمیه‌ها و محدودیت‌ها ────────────────────────────────
    max_upload_mb: int = Field(default=50, ge=1, le=5_120)
    max_room_storage_mb: int = Field(default=2_048, ge=1, le=102_400)
    max_user_storage_mb: int = Field(default=10_240, ge=1, le=1_048_576)
    max_rooms_per_user: int = Field(default=50, ge=1, le=10_000)
    min_room_capacity: int = Field(default=1, ge=1, le=100)
    max_room_capacity: int = Field(default=100, ge=1, le=1_000)
    max_speaker_name_length: int = Field(default=120, ge=1, le=200)
    max_room_name_length: int = Field(default=160, ge=1, le=200)
    max_description_length: int = Field(default=4_000, ge=0, le=20_000)
    allowed_upload_extensions: str = DEFAULT_ALLOWED_EXTENSIONS

    # ── ضبط صوت ──────────────────────────────────────────────
    max_recording_minutes: int = Field(default=180, ge=1, le=1_440)
    recording_bitrate_kbps: int = Field(default=32, ge=8, le=512)
    recording_chunk_seconds: int = Field(default=5, ge=1, le=60)
    recording_abandon_minutes: int = Field(default=30, ge=1, le=10_080)
    recording_max_chunks: int = Field(default=40_000, ge=10, le=1_000_000)

    # ── نشست و کوکی ──────────────────────────────────────────
    session_idle_minutes: int = Field(default=720, ge=1, le=525_600)
    session_absolute_days: int = Field(default=30, ge=1, le=365)
    cookie_name: str = "mas_session"
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    cookie_domain: str = ""

    # ── پروکسی و محدودسازی نرخ ───────────────────────────────
    trusted_proxy_hops: int = Field(default=1, ge=0, le=5)
    login_max_attempts: int = Field(default=10, ge=1, le=1_000)
    login_window_seconds: int = Field(default=600, ge=10, le=86_400)
    register_max_per_ip: int = Field(default=20, ge=1, le=10_000)
    register_window_seconds: int = Field(default=3_600, ge=10, le=604_800)
    public_max_per_ip: int = Field(default=600, ge=10, le=1_000_000)
    public_window_seconds: int = Field(default=60, ge=10, le=86_400)
    api_max_per_minute: int = Field(default=600, ge=10, le=1_000_000)

    # ── اتاق عمومی ───────────────────────────────────────────
    public_state_max_age_seconds: int = Field(default=2, ge=1, le=60)

    # ── نگهداری پس‌زمینه ────────────────────────────────────
    maintenance_enabled: bool = True
    maintenance_interval_seconds: int = Field(default=300, ge=30, le=86_400)
    cleanup_queue_batch: int = Field(default=25, ge=1, le=1_000)

    # ── مدیر ─────────────────────────────────────────────────
    bootstrap_admin_username: str = ""

    # ────────────────────────────────────────────────────────
    # اعتبارسنجی
    # ────────────────────────────────────────────────────────
    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        level = (value or "INFO").strip().upper()
        if level not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
            raise ValueError("MAS_LOG_LEVEL باید یکی از CRITICAL/ERROR/WARNING/INFO/DEBUG باشد.")
        return level

    @field_validator("secret_key", "database_url", "public_base_url", "bootstrap_admin_username", mode="before")
    @classmethod
    def _strip_strings(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("allowed_upload_extensions")
    @classmethod
    def _normalize_extensions(cls, value: str) -> str:
        parts = [p.strip().lower() for p in (value or "").split(",") if p.strip()]
        cleaned: list[str] = []
        for part in parts:
            ext = part if part.startswith(".") else f".{part}"
            # پسوند باید کوتاه و بدون کاراکتر مسیر/کنترلی باشد.
            if len(ext) > 12 or any(c in ext for c in "/\\\x00 ") or not ext[1:].isalnum():
                raise ValueError(f"پسوند مجاز نامعتبر: {part!r}")
            cleaned.append(ext)
        if not cleaned:
            raise ValueError("MAS_ALLOWED_UPLOAD_EXTENSIONS نمی‌تواند خالی باشد.")
        return ",".join(dict.fromkeys(cleaned))

    @model_validator(mode="after")
    def _validate_environment_specific(self) -> Settings:
        production = self.env == "production"

        # ── کلید مخفی ──
        if not self.secret_key:
            if production:
                raise SettingsError(
                    "MAS_SECRET_KEY در production اجباری است. یک مقدار تصادفی بسازید:\n"
                    '    python -c "import secrets; print(secrets.token_urlsafe(48))"'
                )
            self.secret_key = secrets.token_urlsafe(48)
            logger.warning(
                "MAS_SECRET_KEY تنظیم نشده است؛ یک کلید موقت تصادفی ساخته شد. "
                "نشست‌های کاربران با هر بار restart از بین می‌روند. (فقط در %s مجاز است)",
                self.env,
            )
        elif len(self.secret_key) < 32:
            raise SettingsError("MAS_SECRET_KEY باید حداقل ۳۲ کاراکتر باشد.")

        # ── دیتابیس ──
        if not self.database_url:
            if production:
                raise SettingsError(
                    "DATABASE_URL در production اجباری است. بدون آن برنامه روی SQLite محلی "
                    "اجرا می‌شود که در هر deploy/restart پاک می‌گردد (از دست رفتن کل داده‌ها).\n"
                    "مثال: DATABASE_URL=postgresql+psycopg://user:pass@host:5432/mas\n"
                    "اگر واقعاً می‌خواهید در production از SQLite استفاده کنید: "
                    "MAS_ALLOW_SQLITE_IN_PRODUCTION=1"
                )
            self.database_url = f"sqlite:///{(BASE_DIR / 'mas.db').as_posix()}"
        elif production and self.database_url.startswith("sqlite") and not self.allow_sqlite_in_production:
            raise SettingsError(
                "استفاده از SQLite در production غیرفعال است چون داده‌ها در هر استقرار پاک می‌شوند. "
                "DATABASE_URL را به PostgreSQL تغییر دهید یا (با پذیرش ریسک) "
                "MAS_ALLOW_SQLITE_IN_PRODUCTION=1 را تنظیم کنید."
            )

        # ── کوکی امن ──
        if production and not self.cookie_secure:
            logger.warning("MAS_COOKIE_SECURE در production به‌صورت خودکار فعال شد (کوکی فقط روی HTTPS).")
            self.cookie_secure = True

        # ── S3 ──
        if self.storage_backend == "s3":
            missing = [
                name
                for name, value in (
                    ("MAS_S3_BUCKET", self.s3_bucket),
                    ("MAS_S3_ACCESS_KEY_ID", self.s3_access_key_id),
                    ("MAS_S3_SECRET_ACCESS_KEY", self.s3_secret_access_key),
                    ("MAS_S3_REGION", self.s3_region),
                )
                if not value
            ]
            if missing:
                raise SettingsError(
                    f"MAS_STORAGE_BACKEND=s3 است ولی این متغیرها تنظیم نشده‌اند: {', '.join(missing)}. "
                    "همچنین باید requirements-s3.txt (boto3) نصب شود."
                )

        # ── منطق سهمیه‌ها ──
        if self.min_room_capacity > self.max_room_capacity:
            raise SettingsError("MAS_MIN_ROOM_CAPACITY نمی‌تواند از MAS_MAX_ROOM_CAPACITY بزرگ‌تر باشد.")
        if self.max_room_storage_mb < self.max_upload_mb:
            raise SettingsError("MAS_MAX_ROOM_STORAGE_MB باید حداقل به اندازهٔ MAS_MAX_UPLOAD_MB باشد.")
        return self

    # ────────────────────────────────────────────────────────
    # مقادیر مشتق‌شده
    # ────────────────────────────────────────────────────────
    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def max_room_storage_bytes(self) -> int:
        return self.max_room_storage_mb * 1024 * 1024

    @property
    def max_user_storage_bytes(self) -> int:
        return self.max_user_storage_mb * 1024 * 1024

    @property
    def max_recording_seconds(self) -> int:
        return self.max_recording_minutes * 60

    @property
    def max_recording_bytes(self) -> int:
        """سقف تقریبی بایت برای یک ضبط، بر اساس بیت‌ریت و سقف مدت."""
        return int(self.recording_bitrate_kbps * 1000 / 8 * self.max_recording_seconds) + 65_536

    @property
    def allowed_extensions(self) -> frozenset[str]:
        return frozenset(self.allowed_upload_extensions.split(","))

    @property
    def resolved_storage_dir(self) -> Path:
        path = Path(self.storage_dir).expanduser()
        return path if path.is_absolute() else (BASE_DIR / path).resolve()

    @property
    def docs_enabled(self) -> bool:
        if self.enable_docs is not None:
            return self.enable_docs
        return not self.is_production

    @property
    def session_idle_seconds(self) -> int:
        return self.session_idle_minutes * 60

    @property
    def session_absolute_seconds(self) -> int:
        return self.session_absolute_days * 86_400

    @property
    def recording_abandon_seconds(self) -> int:
        return self.recording_abandon_minutes * 60

    def safe_summary(self) -> dict[str, Any]:
        """خلاصهٔ قابل‌لاگ (بدون نشتی مقادیر محرمانه)."""
        url = self.database_url
        if "@" in url and "://" in url:
            scheme, rest = url.split("://", 1)
            _creds, _, host = rest.rpartition("@")
            url = f"{scheme}://***:***@{host}"
        return {
            "env": self.env,
            "database": url,
            "storage_backend": self.storage_backend,
            "storage_dir": str(self.resolved_storage_dir) if self.storage_backend == "local" else self.s3_bucket,
            "max_upload_mb": self.max_upload_mb,
            "max_room_storage_mb": self.max_room_storage_mb,
            "max_user_storage_mb": self.max_user_storage_mb,
            "max_rooms_per_user": self.max_rooms_per_user,
            "max_recording_minutes": self.max_recording_minutes,
            "cookie_secure": self.cookie_secure,
            "trusted_proxy_hops": self.trusted_proxy_hops,
            "secret_key_set": bool(self.secret_key),
            "migrations_on_startup": self.run_migrations_on_startup,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """نمونهٔ پیش‌فرض تنظیمات (از محیط/.env). تست‌ها باید Settings خود را بسازند."""
    return Settings()


def load_settings(**overrides: Any) -> Settings:
    """ساخت تنظیمات با امکان override — استفاده در تست و اسکریپت‌ها."""
    return Settings(**overrides)
