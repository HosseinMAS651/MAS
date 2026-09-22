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
    CleanupQueue,
    Room,
    RoomState,
    Speaker,
    SpeakerTimerState,
    SpeechFile,
    User,
)
from ..storage.base import StorageBackend
from .audit import log_event


class RoomService:
    def __init__(
        self,
        settings: Settings,
        storage: StorageBackend,
        security: SecurityManager,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.security = security

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
        ip: str = "",
    ) -> Room:
        # بررسی سقف تعداد اتاق کاربر
        user_rooms_count = session.execute(
            select(func.count(Room.id)).where(Room.owner_id == owner.id)
        ).scalar() or 0
        if user_rooms_count >= self.settings.max_rooms_per_user:
            raise QuotaExceededError(
                f"شما به سقف مجاز ساخت اتاق ({self.settings.max_rooms_per_user} اتاق) رسیده‌اید."
            )

        capacity = max(1, min(self.settings.max_room_capacity, capacity))
        now_ms = utc_now_ms()

        pub_token = self.security.generate_public_token() if public_enabled else None

        room = Room(
            owner_id=owner.id,
            name=normalize_persian_text(name),
            capacity=capacity,
            description=normalize_persian_text(description),
            recording_enabled=recording_enabled,
            live_files_enabled=live_files_enabled,
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
            actor_user_id=owner.id,
            actor_username=owner.username,
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
        confirm_shrink: bool = False,
        ip: str = "",
    ) -> Room:
        now_ms = utc_now_ms()
        room.name = normalize_persian_text(name)
        room.description = normalize_persian_text(description)
        room.recording_enabled = recording_enabled
        room.live_files_enabled = live_files_enabled
        room.timing_mode = timing_mode if timing_mode in ["global", "individual"] else "global"
        room.global_seconds = max(10, min(86400, global_seconds))
        room.order_mode = order_mode if order_mode in ["manual", "alpha", "age"] else "manual"

        # مدیریت لینک عمومی اتاق
        if public_enabled and not room.public_token:
            room.public_token = self.security.generate_public_token()
            room.public_token_created_at_ms = now_ms
        room.public_enabled = public_enabled

        # مدیریت تغییر ظرفیت و محافظت در برابر باگ C-04
        target_capacity = max(1, min(self.settings.max_room_capacity, capacity))
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

            # در صورت تأیید، سخنران‌های اضافی حذف شوند
            for sp in speakers_to_truncate:
                for f in sp.files:
                    if f.upload_type != "recording":
                        session.add(
                            CleanupQueue(
                                backend=f.backend,
                                storage_key=f.storage_key,
                                reason="capacity_shrink",
                            )
                        )
                        room.storage_used_bytes = max(0, room.storage_used_bytes - f.size_bytes)
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

        room.capacity = target_capacity
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
        # صف‌بندی تمام فایل‌ها برای حذف قطعی
        for f in room.files:
            session.add(
                CleanupQueue(
                    backend=f.backend,
                    storage_key=f.storage_key,
                    reason="room_deleted",
                )
            )

        if room.owner:
            room.owner.storage_used_bytes = max(
                0, room.owner.storage_used_bytes - room.storage_used_bytes
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
    ) -> SpeechFile:
        """آپلود فایل مشترک یا اختصاصی سخنران با رعایت دقیق سهمیه‌ها."""
        if upload_type not in ["common", "speaker"]:
            raise ValidationAppError("نوع آپلود نامعتبر است.")

        clean_filename = sanitize_filename(filename, fallback="file.bin")
        ext = "." + clean_filename.split(".")[-1].lower() if "." in clean_filename else ""
        if ext not in self.settings.allowed_extensions:
            raise FileUploadError(
                f"فرمت فایل مجاز نیست ({ext}). فرمت‌های مجاز: {', '.join(sorted(self.settings.allowed_extensions))}"
            )

        now_ms = utc_now_ms()
        safe_key = f"files/{room.id}/{now_ms}_{clean_filename}"

        # ذخیرهٔ جریانی روی سیستم ذخیره‌سازی (I/O ایمن بدون مسدودسازی)
        size_bytes, sha256_hash = await self.storage.save_stream(safe_key, stream)

        # بررسی سقف اندازهٔ فایل
        if size_bytes > self.settings.max_upload_bytes:
            await self.storage.delete(safe_key)
            size_mb = size_bytes // (1024 * 1024)
            raise QuotaExceededError(
                f"حجم فایل ({size_mb} مگابایت) از سقف مجاز ({self.settings.max_upload_mb} مگابایت) بیشتر است."
            )

        # بررسی سقف ذخیره‌سازی اتاق و کاربر
        if (room.storage_used_bytes + size_bytes) > self.settings.max_room_storage_bytes:
            await self.storage.delete(safe_key)
            raise QuotaExceededError("فضای ذخیره‌سازی اختصاص داده شده به این اتاق پر شده است.")

        if room.owner and (room.owner.storage_used_bytes + size_bytes) > self.settings.max_user_storage_bytes:
            await self.storage.delete(safe_key)
            raise QuotaExceededError("سقف کل فضای حساب کاربری شما تکمیل شده است.")

        sp_name = ""
        if speaker_id:
            sp = session.execute(
                select(Speaker).where(Speaker.id == speaker_id, Speaker.room_id == room.id)
            ).scalar_one_or_none()
            if sp:
                sp_name = sp.name

        speech_file = SpeechFile(
            room_id=room.id,
            speaker_id=speaker_id,
            filename=clean_filename,
            storage_key=safe_key,
            backend=self.settings.storage_backend,
            content_type=content_type or "application/octet-stream",
            size_bytes=size_bytes,
            upload_type=upload_type,
            speaker_name=sp_name,
            sha256=sha256_hash,
            created_at_ms=now_ms,
            updated_at_ms=now_ms,
        )
        session.add(speech_file)

        room.storage_used_bytes += size_bytes
        if room.owner:
            room.owner.storage_used_bytes += size_bytes

        session.flush()
        return speech_file

    def delete_speech_file(self, session: Session, room: Room, file_id: int) -> None:
        """حذف فایل و ثبت در صف پاک‌سازی فیزیکی."""
        file = session.execute(
            select(SpeechFile).where(SpeechFile.id == file_id, SpeechFile.room_id == room.id)
        ).scalar_one_or_none()
        if not file:
            raise NotFoundError("فایل مورد نظر یافت نشد.")

        room.storage_used_bytes = max(0, room.storage_used_bytes - file.size_bytes)
        if room.owner:
            room.owner.storage_used_bytes = max(0, room.owner.storage_used_bytes - file.size_bytes)

        session.add(
            CleanupQueue(
                backend=file.backend,
                storage_key=file.storage_key,
                reason="user_deleted",
            )
        )
        session.delete(file)
        session.flush()
