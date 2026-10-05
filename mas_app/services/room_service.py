"""سرویس مدیریت اتاق‌ها و فایل‌ها.

باگ‌های برطرف‌شده در این سرویس:
- **C-04**: جلوگیری از حذف ناخواسته و بی‌صدای سخنران‌ها در زمان کاهش ظرفیت اتاق (نیاز به تأییدیه صریح).
- **C-06**: جلوگیری از پاک شدن فایل در صورت خطای دیتابیس (نظم دقیق در ترتیب ذخیره و Commit).
- **C-07**: عملیات حذف اتاق با پاک‌سازی کامل و امن کلیه فایل‌ها، ضبط‌ها و رکوردهای وابسته.
- **BE-04**: حذف رفتارهای تصادفی در ذخیرهٔ ترتیب سخنران‌ها.
- **BE-05**: اعتبارسنجی یکپارچهٔ حداقل ظرفیت (حداقل ۱ نفر).
"""

from __future__ import annotations

import io
import secrets
from collections.abc import AsyncIterator

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..core.errors import (
    AppError,
    FileUploadError,
    NotFoundError,
    QuotaExceededError,
    ValidationAppError,
)
from ..core.security import SecurityManager, normalize_persian_text, sanitize_filename
from ..core.timeutil import utc_now_ms
from ..db.models import (
    RecordingChunk,
    RecordingSession,
    Room,
    RoomState,
    Speaker,
    SpeakerTimerState,
    SpeechFile,
    User,
)
from ..storage.base import StorageBackend
from .audit import log_event
from .cleanup_queue import enqueue_cleanup

SPEAKER_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
SAFE_MIME_BY_EXTENSION = {
    ".pdf": "application/pdf",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".rtf": "application/rtf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".odt": "application/vnd.oasis.opendocument.text",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".odp": "application/vnd.oasis.opendocument.presentation",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ods": "application/vnd.oasis.opendocument.spreadsheet",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/ogg",
    ".wav": "audio/wav",
    ".flac": "audio/flac",
    ".weba": "audio/webm",
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".webm": "video/webm",
    ".ogv": "video/ogg",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
}


class _LimitedStream:
    """Stop an upload as soon as it crosses the configured byte ceiling."""

    def __init__(self, source: AsyncIterator[bytes], limit: int) -> None:
        self._source = source
        self._limit = limit
        self._seen = 0

    def __aiter__(self):
        return self

    async def __anext__(self) -> bytes:
        chunk = await self._source.__anext__()
        self._seen += len(chunk)
        if self._seen > self._limit:
            raise QuotaExceededError("حجم فایل از سقف مجاز بیشتر است.")
        return chunk



class RoomService:

    @staticmethod
    def apply_room_speaker_order(session: Session, room: Room) -> None:
        """مرتب‌سازی خودکار سخنرانان در صورت فعال بودن حالت‌های غیر دستی (alpha/age)."""
        if room.order_mode not in ("alpha", "age"):
            return

        speakers = list(room.speakers)
        if len(speakers) <= 1:
            return

        if room.order_mode == "alpha":
            sorted_sp = sorted(
                speakers,
                key=lambda s: (0 if s.name.strip() else 1, s.name.strip().lower(), s.id)
            )
        else:  # age: بزرگ‌تر به کوچک‌تر
            sorted_sp = sorted(
                speakers,
                key=lambda s: (0 if s.age is not None else 1, -(s.age or 0), s.name.strip().lower(), s.id)
            )

        for idx, sp in enumerate(sorted_sp):
            sp.order_index = 100_000 + idx
        session.flush()

        for idx, sp in enumerate(sorted_sp):
            sp.order_index = idx
        session.flush()

    def __init__(
        self,
        settings: Settings,
        storage: StorageBackend,
        security: SecurityManager,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.security = security

    def ensure_speaker_code(self, session: Session, room: Room, speaker: Speaker) -> str:
        """Ensure one encrypted, unique four-character access code exists."""
        if speaker.speaker_code_hash and speaker.speaker_code_encrypted:
            return self.security.decrypt_secret(speaker.speaker_code_encrypted)

        existing_hashes = set(
            session.execute(
                select(Speaker.speaker_code_hash).where(
                    Speaker.room_id == room.id,
                    Speaker.speaker_code_hash.is_not(None),
                    Speaker.id != speaker.id,
                )
            ).scalars().all()
        )
        for _ in range(100):
            code = "".join(secrets.choice(SPEAKER_CODE_ALPHABET) for _ in range(4))
            digest = self.security.hash_token(f"speaker-code:{room.id}:{code}")
            if digest not in existing_hashes:
                speaker.speaker_code_hash = digest
                speaker.speaker_code_encrypted = self.security.encrypt_secret(code)
                return code
        raise RuntimeError("Unable to generate a unique speaker access code for this room.")

    def rotate_speaker_code(self, session: Session, room: Room, speaker_id: int) -> str:
        room = self._lock_room(session, room.id)
        speaker = session.execute(
            select(Speaker).where(Speaker.id == speaker_id, Speaker.room_id == room.id).with_for_update()
        ).scalar_one_or_none()
        if not speaker:
            raise NotFoundError("سخنران مورد نظر یافت نشد.")
        active_recording = session.execute(
            select(RecordingSession.id).where(
                RecordingSession.room_id == room.id,
                RecordingSession.speaker_id == speaker.id,
                RecordingSession.status.in_(("recording", "paused", "finalizing")),
            ).limit(1)
        ).scalar_one_or_none()
        if active_recording is not None:
            raise AppError(
                "تا پایان یا ذخیرهٔ ضبط فعال این سخنران، کد را نمی‌توان تعویض کرد.",
                code="ACTIVE_RECORDING_BLOCKS_CODE_ROTATION",
                status_code=409,
            )
        speaker.speaker_code_hash = None
        speaker.speaker_code_encrypted = None
        speaker.speaker_session_hash = None
        speaker.presence_status = "offline"
        speaker.presence_last_seen_at_ms = 0
        code = self.ensure_speaker_code(session, room, speaker)
        speaker.updated_at_ms = utc_now_ms()
        session.flush()
        return code

    def speaker_code_for_owner(self, speaker: Speaker) -> str | None:
        if not speaker.speaker_code_encrypted:
            return None
        return self.security.decrypt_secret(speaker.speaker_code_encrypted)

    def expire_speaker_presence(self, session: Session, room: Room) -> None:
        cutoff_ms = utc_now_ms() - 60_000
        changed = False
        for speaker in room.speakers:
            if speaker.speaker_session_hash and speaker.presence_last_seen_at_ms <= cutoff_ms:
                speaker.speaker_session_hash = None
                speaker.presence_status = "offline"
                changed = True
        if changed:
            session.flush()

    def _validate_room_text(self, name: str, description: str) -> None:
        if len((name or "").strip()) > self.settings.max_room_name_length:
            raise ValidationAppError(
                f"نام اتاق نمی‌تواند بیش از {self.settings.max_room_name_length} نویسه باشد."
            )
        if len(description or "") > self.settings.max_description_length:
            raise ValidationAppError(
                f"توضیحات نمی‌تواند بیش از {self.settings.max_description_length} نویسه باشد."
            )

    def _lock_room(self, session: Session, room_id: int) -> Room:
        room = session.execute(
            select(Room).where(Room.id == room_id).with_for_update()
        ).scalar_one_or_none()
        if not room:
            raise NotFoundError("اتاق مورد نظر یافت نشد.")
        return room

    @staticmethod
    def _lock_owner(session: Session, owner_id: int) -> User | None:
        return session.execute(
            select(User)
            .where(User.id == owner_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()

    def list_rooms_for_user(self, session: Session, user_id: int) -> list[Room]:
        return session.execute(
            select(Room).where(Room.owner_id == user_id).order_by(Room.id.desc())
        ).scalars().all()

    def get_room_for_user(self, session: Session, room_id: int, user: User) -> Room:
        room = session.execute(
            select(Room).where(Room.id == room_id)
        ).scalar_one_or_none()
        if not room:
            raise NotFoundError("اتاق مورد نظر یافت نشد.")

        # دسترسی فقط برای مالک یا ادمین
        if room.owner_id != user.id and user.role != "admin":
            raise NotFoundError("اتاق مورد نظر یافت نشد.")

        return room

    def get_room_by_public_token(self, session: Session, token: str) -> Room:
        if not token:
            raise NotFoundError("لینک تماشاگر نامعتبر است.")
        room = session.execute(
            select(Room).where(Room.public_token == token, Room.public_enabled == True)  # noqa: E712
        ).scalar_one_or_none()
        if not room:
            raise NotFoundError("اتاق عمومی یافت نشد یا دسترسی عمومی غیرفعال شده است.")
        return room

    def create_room(
        self,
        session: Session,
        owner: User,
        *,
        name: str,
        capacity: int = 10,
        description: str = "",
        recording_enabled: bool = False,
        live_files_enabled: bool = False,
        timing_mode: str = "global",
        global_seconds: int = 300,
        order_mode: str = "manual",
        public_enabled: bool = False,
        speaker_mode_enabled: bool = False,
        speaker_uploads_enabled: bool = False,
        ip: str = "",
    ) -> Room:
        # بررسی سقف تعداد اتاق کاربر
        locked_owner = session.execute(
            select(User).where(User.id == owner.id).with_for_update()
        ).scalar_one()
        user_rooms_count = session.execute(
            select(func.count(Room.id)).where(Room.owner_id == locked_owner.id)
        ).scalar() or 0
        if user_rooms_count >= self.settings.max_rooms_per_user:
            raise QuotaExceededError(
                f"شما به سقف مجاز ساخت اتاق ({self.settings.max_rooms_per_user} اتاق) رسیده‌اید."
            )

        capacity = max(self.settings.min_room_capacity, min(self.settings.max_room_capacity, capacity))
        self._validate_room_text(name, description)
        now_ms = utc_now_ms()

        pub_token = self.security.generate_public_token() if public_enabled else None

        room = Room(
            owner_id=locked_owner.id,
            name=normalize_persian_text(name),
            capacity=capacity,
            description=normalize_persian_text(description),
            recording_enabled=recording_enabled and not speaker_mode_enabled,
            live_files_enabled=live_files_enabled,
            speaker_mode_enabled=speaker_mode_enabled,
            speaker_uploads_enabled=speaker_mode_enabled and speaker_uploads_enabled,
            timing_mode=timing_mode if timing_mode in ["global", "individual"] else "global",
            global_seconds=max(10, min(86400, global_seconds)),
            order_mode=order_mode if order_mode in ["manual", "alpha", "age"] else "manual",
            storage_used_bytes=0,
            public_enabled=public_enabled,
            public_token=pub_token,
            public_token_created_at_ms=now_ms if public_enabled else 0,
            created_at_ms=now_ms,
            updated_at_ms=now_ms,
            version=1,
        )
        session.add(room)
        session.flush()

        # ساخت اسلات‌های اولیهٔ سخنران به تعداد ظرفیت
        for i in range(capacity):
            sp = Speaker(
                room_id=room.id,
                order_index=i,
                name="",
                gender="",
                description="",
                speaking_seconds=room.global_seconds,
                is_finished=False,
                finished_at_ms=0,
                created_at_ms=now_ms,
                updated_at_ms=now_ms,
            )
            session.add(sp)
            session.flush()

            timer = SpeakerTimerState(
                room_id=room.id,
                speaker_id=sp.id,
                elapsed_ms=0,
                overtime_ms=0,
                started_at_ms=0,
                updated_at_ms=now_ms,
                version=1,
            )
            session.add(timer)

        if room.speaker_mode_enabled:
            for speaker in room.speakers:
                self.ensure_speaker_code(session, room, speaker)

        # ایجاد ردیف اولیه RoomState
        first_sp = room.speakers[0] if room.speakers else None
        state = RoomState(
            room_id=room.id,
            current_speaker_id=first_sp.id if first_sp else None,
            current_index=0,
            running=False,
            awaiting_decision=False,
            started_at_ms=0,
            elapsed_ms=0,
            overtime_ms=0,
            stop_reason="",
            updated_at_ms=now_ms,
            version=1,
        )
        session.add(state)
        session.flush()

        log_event(
            session,
            action="room_created",
            actor_user_id=locked_owner.id,
            actor_username=locked_owner.username,
            target_type="room",
            target_id=str(room.id),
            detail={"name": room.name, "capacity": room.capacity},
            ip=ip,
        )
        return room

    def update_room(
        self,
        session: Session,
        room: Room,
        *,
        name: str,
        capacity: int,
        description: str = "",
        recording_enabled: bool = False,
        live_files_enabled: bool = False,
        timing_mode: str = "global",
        global_seconds: int = 300,
        order_mode: str = "manual",
        public_enabled: bool = False,
        speaker_mode_enabled: bool | None = None,
        speaker_uploads_enabled: bool | None = None,
        confirm_shrink: bool = False,
        ip: str = "",
    ) -> Room:
        room = self._lock_room(session, room.id)
        target_speaker_mode = (
            room.speaker_mode_enabled if speaker_mode_enabled is None else speaker_mode_enabled
        )
        was_speaker_mode = room.speaker_mode_enabled
        if not was_speaker_mode and target_speaker_mode:
            active_recording = session.execute(
                select(RecordingSession.id).where(
                    RecordingSession.room_id == room.id,
                    RecordingSession.status.in_(("recording", "paused", "finalizing")),
                ).limit(1)
            ).scalar_one_or_none()
            if active_recording is not None:
                raise AppError(
                    "پیش از فعال‌کردن حالت سخنران، ضبط فعلی را پایان دهید یا ذخیره کنید.",
                    code="ACTIVE_RECORDING_BLOCKS_SPEAKER_MODE",
                    status_code=409,
                )
        if was_speaker_mode and not target_speaker_mode:
            active_speaker_recording = session.execute(
                select(RecordingSession.id).where(
                    RecordingSession.room_id == room.id,
                    RecordingSession.speaker_id.is_not(None),
                    RecordingSession.status.in_(("recording", "paused", "finalizing")),
                ).limit(1)
            ).scalar_one_or_none()
            if active_speaker_recording is not None:
                raise AppError(
                    "پیش از غیرفعال‌کردن حالت سخنران، ضبط‌های فعال/متوقف‌شدهٔ دستگاه‌ها را پایان دهید.",
                    code="ACTIVE_SPEAKER_RECORDING_BLOCKS_DISABLE",
                    status_code=409,
                )
        if not recording_enabled and not target_speaker_mode:
            active_recording = session.execute(
                select(RecordingSession.id).where(
                    RecordingSession.room_id == room.id,
                    RecordingSession.status.in_(("recording", "paused", "finalizing")),
                ).limit(1)
            ).scalar_one_or_none()
            if active_recording is not None:
                raise AppError(
                    "تا زمانی که ضبط فعال این اتاق تعیین تکلیف نشده، امکان غیرفعال کردن ضبط وجود ندارد.",
                    code="ACTIVE_RECORDING_BLOCKS_DISABLE",
                    status_code=409,
                )
        self._validate_room_text(name, description)
        now_ms = utc_now_ms()
        room.name = normalize_persian_text(name)
        room.description = normalize_persian_text(description)
        # Speaker mode always records on the speaker's own device; never start a
        # second, competing capture on the owner's timer page.
        room.recording_enabled = recording_enabled and not target_speaker_mode
        room.live_files_enabled = live_files_enabled
        room.speaker_mode_enabled = target_speaker_mode
        if speaker_uploads_enabled is not None:
            room.speaker_uploads_enabled = speaker_uploads_enabled
        room.timing_mode = timing_mode if timing_mode in ["global", "individual"] else "global"
        room.global_seconds = max(10, min(86400, global_seconds))
        room.order_mode = order_mode if order_mode in ["manual", "alpha", "age"] else "manual"

        if target_speaker_mode:
            for speaker in room.speakers:
                self.ensure_speaker_code(session, room, speaker)
        elif was_speaker_mode:
            for speaker in room.speakers:
                speaker.speaker_session_hash = None
                speaker.presence_status = "offline"

        # مدیریت لینک عمومی اتاق
        if public_enabled and not room.public_token:
            room.public_token = self.security.generate_public_token()
            room.public_token_created_at_ms = now_ms
        room.public_enabled = public_enabled

        # مدیریت تغییر ظرفیت و محافظت در برابر باگ C-04
        target_capacity = max(self.settings.min_room_capacity, min(self.settings.max_room_capacity, capacity))
        current_speakers = sorted(room.speakers, key=lambda s: s.order_index)

        if target_capacity < len(current_speakers):
            # بررسی اینکه آیا سخنران دارای نام یا فایلی در بخش حذفی هست یا نه
            speakers_to_truncate = current_speakers[target_capacity:]
            named_or_with_files = [
                s for s in speakers_to_truncate if (s.name.strip() or len(s.files) > 0)
            ]

            if named_or_with_files and not confirm_shrink:
                affected_names = [s.name for s in named_or_with_files if s.name.strip()]
                preview_names = ", ".join(affected_names[:3])
                raise AppError(
                    f"کاهش ظرفیت منجر به حذف {len(named_or_with_files)} سخنران ثبت‌شده ({preview_names}) "
                    "یا فایل‌های اختصاصی آن‌ها می‌شود. لطفاً ابتدا تأیید کنید.",
                    code="CONFIRM_CAPACITY_SHRINK_REQUIRED",
                    details={"affected_count": len(named_or_with_files)},
                    status_code=409,
                )

            # در صورت تأیید، حذف فقط وقتی مجاز است که ضبط فعالی در حال اجرا نباشد.
            active_recording = session.execute(
                select(RecordingSession.id).where(
                    RecordingSession.room_id == room.id,
                    RecordingSession.speaker_id.in_([sp.id for sp in speakers_to_truncate]),
                    RecordingSession.status.in_(["recording", "paused", "finalizing"]),
                ).limit(1)
            ).scalar_one_or_none()
            if active_recording:
                raise AppError(
                    "برای کاهش ظرفیت ابتدا ضبط فعال سخنران موردنظر را پایان دهید.",
                    code="ACTIVE_RECORDING_BLOCKS_SHRINK",
                    status_code=409,
                )

            # Lock the shared owner row before changing its cross-room quota counter.
            locked_owner = self._lock_owner(session, room.owner_id)
            # در صورت تأیید، سخنران‌های اضافی حذف شوند
            for sp in speakers_to_truncate:
                for f in sp.files:
                    if f.upload_type != "recording":
                        enqueue_cleanup(session, backend=f.backend, storage_key=f.storage_key, reason="capacity_shrink")
                        room.storage_used_bytes = max(0, room.storage_used_bytes - f.size_bytes)
                        if locked_owner:
                            locked_owner.storage_used_bytes = max(
                                0, locked_owner.storage_used_bytes - f.size_bytes
                            )
                session.delete(sp)
            session.flush()

        elif target_capacity > len(current_speakers):
            # افزودن اسلات‌های جدید
            diff = target_capacity - len(current_speakers)
            start_idx = len(current_speakers)
            for i in range(diff):
                sp = Speaker(
                    room_id=room.id,
                    order_index=start_idx + i,
                    name="",
                    gender="",
                    description="",
                    speaking_seconds=room.global_seconds,
                    is_finished=False,
                    finished_at_ms=0,
                    created_at_ms=now_ms,
                    updated_at_ms=now_ms,
                )
                session.add(sp)
                session.flush()

                timer = SpeakerTimerState(
                    room_id=room.id,
                    speaker_id=sp.id,
                    elapsed_ms=0,
                    overtime_ms=0,
                    started_at_ms=0,
                    updated_at_ms=now_ms,
                    version=1,
                )
                session.add(timer)
                if target_speaker_mode:
                    self.ensure_speaker_code(session, room, sp)

        room.capacity = target_capacity

        # اگر سخنران فعلی حذف شده یا اندیس فعلی بعد از shrink جابه‌جا شده است، state را
        # به اولین سخنران معتبر همگام می‌کنیم.
        speakers_now = session.execute(
            select(Speaker).where(Speaker.room_id == room.id).order_by(Speaker.order_index.asc())
        ).scalars().all()
        if room.state:
            current = next((s for s in speakers_now if s.id == room.state.current_speaker_id), None)
            if current is None:
                current = next(
                    (speaker for speaker in speakers_now if not speaker.is_finished),
                    speakers_now[0] if speakers_now else None,
                )
                room.state.current_speaker_id = current.id if current else None
                room.state.current_index = speakers_now.index(current) if current else 0
                room.state.running = False
                room.state.awaiting_decision = False
                room.state.started_at_ms = 0
                room.state.elapsed_ms = current.timer.elapsed_ms if current and current.timer else 0
                room.state.overtime_ms = current.timer.overtime_ms if current and current.timer else 0
                room.state.stop_reason = "switched" if current else ""
            else:
                room.state.current_index = speakers_now.index(current)
            room.state.version += 1
            room.state.updated_at_ms = now_ms

        # مرتب‌سازی خودکار در صورت تغییر حالت به غیر دستی
        self.apply_room_speaker_order(session, room)

        room.updated_at_ms = now_ms
        room.version += 1
        session.flush()
        return room

    def rotate_public_token(self, session: Session, room: Room) -> str:
        """تولید یک توکن جدید برای لینک عمومی و باطل کردن توکن قبلی."""
        new_token = self.security.generate_public_token()
        room.public_token = new_token
        room.public_token_created_at_ms = utc_now_ms()
        room.public_enabled = True
        session.flush()
        return new_token

    def generate_qr_svg(self, url: str) -> str:
        """ساخت کد QR به‌صورت رشتهٔ SVG بدون وابستگی به فایل دیسک."""
        import qrcode
        import qrcode.image.svg

        factory = qrcode.image.svg.SvgPathImage
        img = qrcode.make(url, image_factory=factory, box_size=10, border=2)
        stream = io.BytesIO()
        img.save(stream)
        return stream.getvalue().decode("utf-8")

    def delete_room(self, session: Session, room: Room, actor: User, ip: str = "") -> None:
        """حذف کامل اتاق و انتقال تمام فایل‌های آن به صف پاک‌سازی."""
        room = self._lock_room(session, room.id)
        # فایل‌های نهایی ثبت‌شده
        for f in room.files:
            enqueue_cleanup(session, backend=f.backend, storage_key=f.storage_key, reason="room_deleted")

        # chunkهای ضبط در speech_files نیستند و باید جداگانه پاک‌سازی شوند؛
        # در غیر این صورت حذف اتاق فقط ردیف DB را حذف می‌کرد و فایل‌های chunk روی دیسک می‌ماندند.
        recording_ids = [
            rid for (rid,) in session.execute(
                select(RecordingSession.id).where(RecordingSession.room_id == room.id)
            ).all()
        ]
        if recording_ids:
            chunks = session.execute(
                select(RecordingChunk).where(RecordingChunk.session_id.in_(recording_ids))
            ).scalars().all()
            for c in chunks:
                enqueue_cleanup(session, backend=c.backend, storage_key=c.storage_key, reason="room_deleted")

        locked_owner = self._lock_owner(session, room.owner_id)
        if locked_owner:
            locked_owner.storage_used_bytes = max(
                0, locked_owner.storage_used_bytes - room.storage_used_bytes
            )

        log_event(
            session,
            action="room_deleted",
            actor_user_id=actor.id,
            actor_username=actor.username,
            severity="warning",
            target_type="room",
            target_id=str(room.id),
            detail={"name": room.name},
            ip=ip,
        )
        session.delete(room)
        session.flush()

    async def upload_speech_file(
        self,
        session: Session,
        room: Room,
        *,
        upload_type: str,
        filename: str,
        content_type: str,
        stream: AsyncIterator[bytes],
        speaker_id: int | None = None,
        approval_status: str = "approved",
    ) -> SpeechFile:
        """آپلود فایل مشترک یا اختصاصی سخنران با رعایت دقیق سهمیه‌ها."""
        if upload_type not in ["common", "speaker"]:
            raise ValidationAppError("نوع آپلود نامعتبر است.")
        if approval_status not in {"pending", "approved", "rejected"}:
            raise ValidationAppError("وضعیت تأیید فایل نامعتبر است.")
        if upload_type == "speaker" and speaker_id is None:
            raise ValidationAppError("فایل اختصاصی باید به یک سخنران متصل باشد.")

        clean_filename = sanitize_filename(filename, fallback="file.bin")
        ext = "." + clean_filename.split(".")[-1].lower() if "." in clean_filename else ""
        if ext not in self.settings.allowed_extensions:
            raise FileUploadError(
                f"فرمت فایل مجاز نیست ({ext}). فرمت‌های مجاز: {', '.join(sorted(self.settings.allowed_extensions))}"
            )

        now_ms = utc_now_ms()
        safe_key = f"files/{room.id}/{now_ms}_{secrets.token_hex(8)}_{clean_filename}"

        # ذخیرهٔ جریانی با سقف سخت، تا فایل بزرگ هرگز کامل روی دیسک نوشته نشود.
        try:
            size_bytes, sha256_hash = await self.storage.save_stream(
                safe_key, _LimitedStream(stream, self.settings.max_upload_bytes)
            )
        except Exception:
            # LocalStorage فایل موقت را خودش جمع می‌کند؛ target نهایی نیز ممکن است در بعضی
            # backendها ساخته شده باشد، بنابراین حذف best-effort انجام می‌شود.
            await self.storage.delete(safe_key)
            raise

        # قفل رکورد اتاق قبل از محاسبهٔ quota تا دو upload همزمان نتوانند از سقف عبور کنند.
        locked_room = self._lock_room(session, room.id)
        owner = self._lock_owner(session, locked_room.owner_id)
        active_recording_statuses = ("recording", "paused", "finalizing")
        room_reserved_bytes = session.execute(
            select(func.coalesce(func.sum(RecordingSession.bytes_received), 0)).where(
                RecordingSession.room_id == locked_room.id,
                RecordingSession.status.in_(active_recording_statuses),
            )
        ).scalar_one()
        if (
            locked_room.storage_used_bytes + int(room_reserved_bytes) + size_bytes
            > self.settings.max_room_storage_bytes
        ):
            await self.storage.delete(safe_key)
            raise QuotaExceededError("فضای ذخیره‌سازی اختصاص داده شده به این اتاق برای این فایل کافی نیست.")

        owner_reserved_bytes = 0
        if owner:
            owner_reserved_bytes = session.execute(
                select(func.coalesce(func.sum(RecordingSession.bytes_received), 0))
                .join(Room, Room.id == RecordingSession.room_id)
                .where(
                    Room.owner_id == owner.id,
                    RecordingSession.status.in_(active_recording_statuses),
                )
            ).scalar_one()
        if (
            owner
            and owner.storage_used_bytes + int(owner_reserved_bytes) + size_bytes
            > self.settings.max_user_storage_bytes
        ):
            await self.storage.delete(safe_key)
            raise QuotaExceededError("سقف کل فضای حساب کاربری شما با احتساب ضبط‌های در حال دریافت کافی نیست.")

        available = self.storage.available_bytes()
        if available is not None and size_bytes > max(0, available - 64 * 1024 * 1024):
            await self.storage.delete(safe_key)
            raise QuotaExceededError("فضای خالی دیسک برای ذخیرهٔ این فایل کافی نیست.")

        sp_name = ""
        if speaker_id is not None:
            sp = session.execute(
                select(Speaker).where(Speaker.id == speaker_id, Speaker.room_id == locked_room.id)
            ).scalar_one_or_none()
            if not sp:
                await self.storage.delete(safe_key)
                raise NotFoundError("سخنران مورد نظر متعلق به این اتاق نیست.")
            sp_name = sp.name

        speech_file = SpeechFile(
            room_id=locked_room.id,
            speaker_id=speaker_id,
            filename=clean_filename,
            storage_key=safe_key,
            backend=self.settings.storage_backend,
            # Never trust multipart Content-Type: infer only a small safe allowlist.
            content_type=SAFE_MIME_BY_EXTENSION.get(ext, "application/octet-stream"),
            size_bytes=size_bytes,
            upload_type=upload_type,
            approval_status=approval_status,
            speaker_name=sp_name,
            sha256=sha256_hash,
            created_at_ms=now_ms,
            updated_at_ms=now_ms,
        )
        session.add(speech_file)
        try:
            session.flush()
        except Exception:
            # فایل فیزیکی در همین عملیات ساخته شده است؛ اگر DB insert شکست خورد
            # باید همان لحظه پاک شود تا orphan و نشت سهمیه ایجاد نشود.
            await self.storage.delete(safe_key)
            raise

        locked_room.storage_used_bytes += size_bytes
        if owner:
            owner.storage_used_bytes += size_bytes

        session.flush()
        return speech_file

    def review_speech_file(
        self, session: Session, room: Room, file_id: int, *, approved: bool
    ) -> SpeechFile:
        room = self._lock_room(session, room.id)
        speech_file = session.execute(
            select(SpeechFile)
            .where(SpeechFile.id == file_id, SpeechFile.room_id == room.id)
            .with_for_update()
        ).scalar_one_or_none()
        if not speech_file or speech_file.upload_type != "speaker":
            raise NotFoundError("فایل سخنران مورد نظر یافت نشد.")
        speech_file.approval_status = "approved" if approved else "rejected"
        speech_file.updated_at_ms = utc_now_ms()
        session.flush()
        return speech_file

    def delete_speech_file(self, session: Session, room: Room, file_id: int) -> None:
        """حذف فایل و ثبت در صف پاک‌سازی فیزیکی."""
        room = self._lock_room(session, room.id)
        file = session.execute(
            select(SpeechFile).where(SpeechFile.id == file_id, SpeechFile.room_id == room.id)
        ).scalar_one_or_none()
        if not file:
            raise NotFoundError("فایل مورد نظر یافت نشد.")

        room.storage_used_bytes = max(0, room.storage_used_bytes - file.size_bytes)
        locked_owner = self._lock_owner(session, room.owner_id)
        if locked_owner:
            locked_owner.storage_used_bytes = max(
                0, locked_owner.storage_used_bytes - file.size_bytes
            )

        enqueue_cleanup(session, backend=file.backend, storage_key=file.storage_key, reason="user_deleted")
        session.delete(file)
        session.flush()
