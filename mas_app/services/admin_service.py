"""سرویس مدیریت مدیر سیستم (Admin Panel)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..core.errors import NotFoundError, ValidationAppError
from ..db.models import AuditLog, Room, SpeechFile, Speaker, User
from .audit import log_event


class AdminService:
    @staticmethod
    def get_stats(session: Session) -> dict[str, Any]:
        users_count = session.execute(select(func.count(User.id))).scalar() or 0
        rooms_count = session.execute(select(func.count(Room.id))).scalar() or 0
        recordings_count = (
            session.execute(
                select(func.count(SpeechFile.id)).where(SpeechFile.upload_type == "recording")
            ).scalar()
            or 0
        )
        total_storage = session.execute(select(func.sum(Room.storage_used_bytes))).scalar() or 0

        return {
            "users_count": users_count,
            "rooms_count": rooms_count,
            "recordings_count": recordings_count,
            "total_storage_bytes": int(total_storage),
        }

    @staticmethod
    def list_users(session: Session, *, limit: int = 50, offset: int = 0) -> list[dict]:
        users = session.execute(
            select(User).order_by(User.id.desc()).offset(offset).limit(limit)
        ).scalars().all()

        counts = dict(
            session.execute(
                select(Room.owner_id, func.count(Room.id))
                .where(Room.owner_id.in_([u.id for u in users]))
                .group_by(Room.owner_id)
            ).all()
        ) if users else {}

        results = []
        for u in users:
            rooms_count = counts.get(u.id, 0)
            results.append(
                {
                    "id": u.id,
                    "username": u.username,
                    "account_name": u.account_name,
                    "role": u.role,
                    "is_active": u.is_active,
                    "rooms_count": rooms_count,
                    "storage_used_bytes": u.storage_used_bytes,
                    "created_at_ms": u.created_at_ms,
                    "last_login_at_ms": u.last_login_at_ms,
                }
            )
        return results

    @staticmethod
    def toggle_user_active(
        session: Session, target_user_id: int, admin_user: User, *, ip: str = ""
    ) -> bool:
        if target_user_id == admin_user.id:
            raise ValidationAppError("امکان غیرفعال کردن حساب کاربری خودتان وجود ندارد.")

        user = session.execute(select(User).where(User.id == target_user_id)).scalar_one_or_none()
        if not user:
            raise NotFoundError("کاربر یافت نشد.")

        user.is_active = not user.is_active
        session.flush()

        log_event(
            session,
            action="admin_toggle_user_active",
            actor_user_id=admin_user.id,
            actor_username=admin_user.username,
            severity="warning",
            target_type="user",
            target_id=str(user.id),
            detail={"is_active": user.is_active},
            ip=ip,
        )
        return user.is_active

    @staticmethod
    def list_rooms(session: Session, *, limit: int = 50, offset: int = 0) -> list[dict]:
        rooms = session.execute(
            select(Room)
            .options(joinedload(Room.owner))
            .order_by(Room.id.desc())
            .offset(offset)
            .limit(limit)
        ).scalars().all()

        speaker_counts = dict(
            session.execute(
                select(Room.id, func.count(Speaker.id))
                .join(Speaker, Speaker.room_id == Room.id, isouter=True)
                .where(Room.id.in_([r.id for r in rooms]))
                .group_by(Room.id)
            ).all()
        ) if rooms else {}

        results = []
        for r in rooms:
            owner_name = r.owner.username if r.owner else "—"
            results.append(
                {
                    "id": r.id,
                    "owner_id": r.owner_id,
                    "owner_username": owner_name,
                    "name": r.name,
                    "capacity": r.capacity,
                    "speakers_count": int(speaker_counts.get(r.id, 0)),
                    "storage_used_bytes": r.storage_used_bytes,
                    "created_at_ms": r.created_at_ms,
                }
            )
        return results

    @staticmethod
    def list_audit_logs(
        session: Session, *, limit: int = 100, offset: int = 0
    ) -> list[AuditLog]:
        return session.execute(
            select(AuditLog).order_by(AuditLog.id.desc()).offset(offset).limit(limit)
        ).scalars().all()
