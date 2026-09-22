"""مدل‌های دادهٔ MAS.

نکته‌های طراحی (که هر کدام یک باگ مشخص از گزارش audit را برطرف می‌کنند):

* **قیدهای CHECK در سطح دیتابیس** برای همهٔ مقادیر حساس (DB-05).
* **کلید خارجی واقعی با ``ondelete`` درست** برای همهٔ ارجاع‌ها، از جمله
  ``room_states.current_speaker_id`` (DB-04).
* **``created_at_ms``/``updated_at_ms``** با مقدار پیش‌فرض واقعی (نه صفر) (DB-07).
* **ایندکس‌های لازم برای کوئری‌های پرتکرار** و بدون ایندکس تکراری (DB-01/DB-06).
* ستون ``version`` به‌صورت **صریح توسط سرویس** افزایش می‌یابد (نه ``version_id_col``
  اتوماتیک) تا تشخیص ویرایش همزمان دقیق باشد و آپلود فایل باعث ۴۰۹ کاذب نشود
  (BE-17).
* نام کاربری در دو ستون نگهداری می‌شود: ``username`` برای نمایش و ``username_key``
  نرمال‌شده برای یکتایی — پس «Ali» و «ali» و «ALI» یک حساب هستند (BE-25).
* وضعیت «پایان یافته» فقط روی ``Speaker.is_finished`` است (منبع یکتا) و
  ``SpeakerTimerState`` تنها زمان‌ها را نگه می‌دارد؛ این کار از ناسازگاری دو
  منبع داده در نسخهٔ قدیم جلوگیری می‌کند.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.timeutil import utc_now_ms
from .base import Base

# ─────────────────────────────────────────────────────────────
# مقادیر مجاز (منبع یکتا برای CHECK constraintها و اعتبارسنجی لایهٔ سرویس)
# ─────────────────────────────────────────────────────────────
USER_ROLES = ("user", "admin")
CALENDARS = ("jalali", "gregorian")
TIMING_MODES = ("global", "individual")
ORDER_MODES = ("manual", "alpha", "age")
GENDERS = ("", "male", "female", "other")
UPLOAD_TYPES = ("common", "speaker", "recording")
RECORDING_STATUSES = (
    "recording",
    "paused",
    "finalizing",
    "saved",
    "discarded",
    "failed",
    "recovered",
)
STOP_REASONS = ("", "paused", "time_up", "finished", "session_completed", "switched")
AUDIT_SEVERITIES = ("info", "warning", "error", "security")
STORAGE_BACKENDS = ("local", "s3")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class User(Base):
    """حساب کاربری."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(f"role IN ({_quoted(USER_ROLES)})", name="role_valid"),
        CheckConstraint(f"calendar IN ({_quoted(CALENDARS)})", name="calendar_valid"),
        CheckConstraint("age IS NULL OR (age >= 1 AND age <= 120)", name="age_range"),
        CheckConstraint("storage_used_bytes >= 0", name="storage_non_negative"),
        CheckConstraint("failed_login_count >= 0", name="failed_login_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: نام کاربری همان‌طور که کاربر وارد کرده (برای نمایش).
    username: Mapped[str] = mapped_column(String(32), nullable=False)
    #: شکل نرمال‌شده (NFC + casefold + یکسان‌سازی ی/ک) برای یکتایی و جست‌وجو.
    username_key: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    account_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    age: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    job: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    profile_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Tehran")
    calendar: Mapped[str] = mapped_column(String(16), nullable=False, default="jalali")
    storage_used_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=utc_now_ms)
    updated_at_ms: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=utc_now_ms, onupdate=utc_now_ms
    )
    last_login_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    rooms: Mapped[list[Room]] = relationship(
        back_populates="owner", cascade="all, delete-orphan", passive_deletes=True
    )
    sessions: Mapped[list[AuthSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:  # pragma: no cover - فقط برای دیباگ
        return f"<User id={self.id} username={self.username!r} role={self.role}>"


class AuthSession(Base):
    """نشست ورود (توکن به‌صورت HMAC در DB، نه متن خام)."""

    __tablename__ = "auth_sessions"
    __table_args__ = (Index("ix_auth_sessions_user_id_expires", "user_id", "expires_at_ms"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    #: HMAC توکن CSRF (نه خود توکن) — باگ BE-28 گزارش audit.
    csrf_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=utc_now_ms)
    expires_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    last_seen_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=utc_now_ms)
    ip: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    user_agent: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    user: Mapped[User] = relationship(back_populates="sessions")


class RateLimitBucket(Base):
    """سطل محدودسازی نرخ (پایدار در DB تا با restart صفر نشود)."""

    __tablename__ = "rate_limit_buckets"
    __table_args__ = (
        CheckConstraint("count >= 0", name="count_non_negative"),
        Index("ix_rate_limit_buckets_window", "window_started_at_ms"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bucket_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    window_started_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=utc_now_ms)
    blocked_until_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class Room(Base):
    """اتاق سخنرانی."""

    __tablename__ = "rooms"
    __table_args__ = (
        CheckConstraint("capacity >= 1", name="capacity_positive"),
        CheckConstraint("global_seconds >= 10 AND global_seconds <= 86400", name="global_seconds_range"),
        CheckConstraint("storage_used_bytes >= 0", name="storage_non_negative"),
        CheckConstraint(f"timing_mode IN ({_quoted(TIMING_MODES)})", name="timing_mode_valid"),
        CheckConstraint(f"order_mode IN ({_quoted(ORDER_MODES)})", name="order_mode_valid"),
        # NOT public_enabled ... → قابل حمل بین SQLite و PostgreSQL (مقایسهٔ بولین با ۰ در PG خطا است)
        CheckConstraint("NOT public_enabled OR public_token IS NOT NULL", name="public_requires_token"),
        Index("ix_rooms_owner_id_id_desc", "owner_id", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    recording_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    live_files_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    #: اتاق عمومی (تماشاگران بدون ورود) — ویژگی جدید.
    public_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    public_token: Mapped[str | None] = mapped_column(String(43), nullable=True, unique=True)
    public_token_created_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    timing_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="global")
    global_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    order_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    storage_used_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=utc_now_ms)
    updated_at_ms: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=utc_now_ms, onupdate=utc_now_ms
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    owner: Mapped[User] = relationship(back_populates="rooms")
    speakers: Mapped[list[Speaker]] = relationship(
        back_populates="room",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Speaker.order_index",
    )
    files: Mapped[list[SpeechFile]] = relationship(
        back_populates="room", cascade="all, delete-orphan", passive_deletes=True
    )
    state: Mapped[RoomState | None] = relationship(
        back_populates="room", uselist=False, cascade="all, delete-orphan", passive_deletes=True
    )
    recording_sessions: Mapped[list[RecordingSession]] = relationship(
        back_populates="room", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Room id={self.id} name={self.name!r} capacity={self.capacity}>"


class Speaker(Base):
    """یک اسلات سخنران در اتاق (می‌تواند خالی/بدون نام باشد)."""

    __tablename__ = "speakers"
    __table_args__ = (
        UniqueConstraint("room_id", "order_index", name="uq_speaker_room_order"),
        CheckConstraint("order_index >= 0", name="order_index_non_negative"),
        CheckConstraint("speaking_seconds >= 10 AND speaking_seconds <= 86400", name="speaking_seconds_range"),
        CheckConstraint("age IS NULL OR (age >= 1 AND age <= 120)", name="age_range"),
        CheckConstraint(f"gender IN ({_quoted(GENDERS)})", name="gender_valid"),
        Index("ix_speakers_room_id_name", "room_id", "name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    gender: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    age: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    speaking_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    is_finished: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    finished_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=utc_now_ms)
    updated_at_ms: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=utc_now_ms, onupdate=utc_now_ms
    )

    room: Mapped[Room] = relationship(back_populates="speakers")
    files: Mapped[list[SpeechFile]] = relationship(back_populates="speaker", passive_deletes=True)
    timer: Mapped[SpeakerTimerState | None] = relationship(
        back_populates="speaker", uselist=False, cascade="all, delete-orphan", passive_deletes=True
    )
    recording_sessions: Mapped[list[RecordingSession]] = relationship(
        back_populates="speaker", passive_deletes=True
    )

    @property
    def is_empty_slot(self) -> bool:
        """اسلات بدون نام (در صفحهٔ اتاق نمایش داده نمی‌شود — باگ FE-08)."""
        return not (self.name or "").strip()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Speaker id={self.id} order={self.order_index} name={self.name!r}>"


class SpeechFile(Base):
    """فایل مشترک، فایل اختصاصی سخنران، یا ضبط صوت ذخیره‌شده."""

    __tablename__ = "speech_files"
    __table_args__ = (
        CheckConstraint(f"upload_type IN ({_quoted(UPLOAD_TYPES)})", name="upload_type_valid"),
        CheckConstraint("size_bytes >= 0", name="size_non_negative"),
        CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="duration_non_negative"),
        Index("ix_speech_files_room_upload_created", "room_id", "upload_type", "created_at_ms"),
        Index("ix_speech_files_upload_type_created", "upload_type", "created_at_ms"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: با حذف سخنران، فایل‌های معمولی توسط سرویس حذف می‌شوند ولی **ضبط‌ها نگه
    #: داشته می‌شوند**؛ بنابراین ``SET NULL`` و نام سخنران در ``speaker_name``
    #: نگهداری می‌شود تا فایل ضبط بی‌صاحب نشود.
    speaker_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("speakers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: نام نمایشی (همان چیزی که کاربر می‌بیند؛ فارسی مجاز است).
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    #: کلید ذخیره‌سازی در بک‌اند (مسیر نسبی برای local، object key برای s3).
    storage_key: Mapped[str] = mapped_column(String(400), nullable=False, unique=True)
    backend: Mapped[str] = mapped_column(String(16), nullable=False, default="local")
    content_type: Mapped[str] = mapped_column(String(120), nullable=False, default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    upload_type: Mapped[str] = mapped_column(String(16), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True, default=None)
    #: نام سخنران در لحظهٔ ضبط (برای ضبط‌ها؛ حتی بعد از حذف سخنران باقی می‌ماند).
    speaker_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=utc_now_ms)
    updated_at_ms: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=utc_now_ms, onupdate=utc_now_ms
    )

    room: Mapped[Room] = relationship(back_populates="files")
    speaker: Mapped[Speaker | None] = relationship(back_populates="files")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SpeechFile id={self.id} filename={self.filename!r} type={self.upload_type}>"


class RoomState(Base):
    """وضعیت اجرای زندهٔ اتاق (یک ردیف برای هر اتاق)."""

    __tablename__ = "room_states"
    __table_args__ = (
        CheckConstraint("elapsed_ms >= 0", name="elapsed_non_negative"),
        CheckConstraint("overtime_ms >= 0", name="overtime_non_negative"),
        CheckConstraint("current_index >= 0", name="current_index_non_negative"),
        CheckConstraint(f"stop_reason IN ({_quoted(STOP_REASONS)})", name="stop_reason_valid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    #: کلید خارجی واقعی با ``SET NULL`` (باگ DB-04: ارجاع معلق بعد از حذف سخنران).
    current_speaker_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("speakers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    current_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    running: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: زمان اصلی تمام شده و منتظر تصمیم کاربر (ادامه / اتمام) است — ویژگی جدید.
    awaiting_decision: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    started_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    elapsed_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    overtime_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    stop_reason: Mapped[str] = mapped_column(String(24), nullable=False, default="")
    updated_at_ms: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=utc_now_ms, onupdate=utc_now_ms
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    room: Mapped[Room] = relationship(back_populates="state")
    current_speaker: Mapped[Speaker | None] = relationship(foreign_keys=[current_speaker_id])


class SpeakerTimerState(Base):
    """زمان مصرف‌شدهٔ هر سخنران (منبع یکتا برای elapsed/overtime)."""

    __tablename__ = "speaker_timer_states"
    __table_args__ = (
        UniqueConstraint("room_id", "speaker_id", name="uq_timer_room_speaker"),
        CheckConstraint("elapsed_ms >= 0", name="elapsed_non_negative"),
        CheckConstraint("overtime_ms >= 0", name="overtime_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    speaker_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("speakers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    elapsed_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    overtime_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    started_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at_ms: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=utc_now_ms, onupdate=utc_now_ms
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    speaker: Mapped[Speaker] = relationship(back_populates="timer")


class RecordingSession(Base):
    """یک نشست ضبط برای یک سخنران (ویژگی جدید: ضبط خودکار و تکه‌ای).

    چرخهٔ زندگی::

        recording → paused → recording → finalizing → saved
                                            ↘ failed / discarded / recovered
    """

    __tablename__ = "recording_sessions"
    __table_args__ = (
        CheckConstraint(f"status IN ({_quoted(RECORDING_STATUSES)})", name="status_valid"),
        CheckConstraint("chunk_seq >= 0", name="chunk_seq_non_negative"),
        CheckConstraint("bytes_received >= 0", name="bytes_non_negative"),
        CheckConstraint("recorded_ms >= 0", name="recorded_ms_non_negative"),
        Index("ix_recording_sessions_room_status", "room_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    speaker_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("speakers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: نام سخنران در لحظهٔ شروع ضبط (برای نام‌گذاری فایل نهایی).
    speaker_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="recording")
    mime_type: Mapped[str] = mapped_column(String(60), nullable=False, default="audio/webm")
    chunk_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bytes_received: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    #: مجموع زمان‌هایی که ضبط **فعال** بوده (سرور این را می‌شمارد، نه کلاینت).
    recorded_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    #: لنگر زمانی بازهٔ فعال فعلی (وقتی paused است صفر می‌شود).
    active_since_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    started_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=utc_now_ms)
    last_chunk_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    ended_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    final_file_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("speech_files.id", ondelete="SET NULL"), nullable=True
    )
    error: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    room: Mapped[Room] = relationship(back_populates="recording_sessions")
    speaker: Mapped[Speaker | None] = relationship(back_populates="recording_sessions")
    final_file: Mapped[SpeechFile | None] = relationship(foreign_keys=[final_file_id])
    chunks: Mapped[list[RecordingChunk]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="RecordingChunk.seq",
    )


class RecordingChunk(Base):
    """یک تکهٔ آپلودشده از ضبط (برای مقاومت در برابر بسته شدن تب)."""

    __tablename__ = "recording_chunks"
    __table_args__ = (
        UniqueConstraint("session_id", "seq", name="uq_chunk_session_seq"),
        CheckConstraint("seq >= 0", name="seq_non_negative"),
        CheckConstraint("size_bytes > 0", name="size_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("recording_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(400), nullable=False, unique=True)
    backend: Mapped[str] = mapped_column(String(16), nullable=False, default="local")
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=utc_now_ms)

    session: Mapped[RecordingSession] = relationship(back_populates="chunks")


class CleanupQueue(Base):
    """صف حذف فایل‌های ذخیره‌سازی (حذف قطعی به‌صورت پس‌زمینه و قابل تکرار)."""

    __tablename__ = "cleanup_queue"
    __table_args__ = (
        UniqueConstraint("backend", "storage_key", name="uq_cleanup_backend_key"),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        Index("ix_cleanup_queue_next_attempt", "next_attempt_at_ms"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    backend: Mapped[str] = mapped_column(String(16), nullable=False, default="local")
    storage_key: Mapped[str] = mapped_column(String(400), nullable=False)
    reason: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=utc_now_ms)
    last_error: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=utc_now_ms)


class AuditLog(Base):
    """لاگ ممیزی/امنیتی (باگ SEC-10: هیچ لاگ امنیتی وجود نداشت)."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint(f"severity IN ({_quoted(AUDIT_SEVERITIES)})", name="severity_valid"),
        Index("ix_audit_logs_action_created", "action", "created_at_ms"),
        Index("ix_audit_logs_actor_created", "actor_user_id", "created_at_ms"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_username: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    action: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    target_type: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    target_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    #: جزئیات به‌صورت JSON رشته‌ای (بدون وابستگی به JSON دیتابیس، برای سازگاری
    #: با همهٔ موتورهای پشتیبانی‌شده).
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ip: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    user_agent: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=utc_now_ms, index=True)


ALL_TABLES: tuple[str, ...] = (
    "users",
    "auth_sessions",
    "rate_limit_buckets",
    "rooms",
    "speakers",
    "speech_files",
    "room_states",
    "speaker_timer_states",
    "recording_sessions",
    "recording_chunks",
    "cleanup_queue",
    "audit_logs",
)
