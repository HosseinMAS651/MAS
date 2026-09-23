"""مسیریاب پنل مدیریت سیستم (Admin)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...db.models import User
from ...schemas.admin import (
    AdminRoomItem,
    AdminStatsResponse,
    AdminUserItem,
    AuditLogItem,
)
from ...services.admin_service import AdminService
from ..deps import (
    get_client_ip,
    get_current_admin,
    get_db,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/stats")
def get_stats(
    admin: Annotated[User, Depends(get_current_admin)],
    session: Annotated[Session, Depends(get_db)],
) -> dict:
    stats = AdminService.get_stats(session)
    return {"ok": True, "stats": AdminStatsResponse(**stats)}


@router.get("/users")
def list_users(
    admin: Annotated[User, Depends(get_current_admin)],
    session: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    users = AdminService.list_users(session, limit=limit, offset=offset)
    return {"ok": True, "users": [AdminUserItem(**u) for u in users]}


@router.post("/users/{user_id}/toggle-active")
def toggle_user_active(
    user_id: int,
    admin: Annotated[User, Depends(get_current_admin)],
    session: Annotated[Session, Depends(get_db)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> dict:
    is_active = AdminService.toggle_user_active(session, user_id, admin, ip=client_ip)
    return {
        "ok": True,
        "is_active": is_active,
        "message": "وضعیت کاربر به‌روزرسانی شد.",
    }


@router.get("/rooms")
def list_rooms(
    admin: Annotated[User, Depends(get_current_admin)],
    session: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    rooms = AdminService.list_rooms(session, limit=limit, offset=offset)
    return {"ok": True, "rooms": [AdminRoomItem(**r) for r in rooms]}


@router.get("/audit-logs")
def list_audit_logs(
    admin: Annotated[User, Depends(get_current_admin)],
    session: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    logs = AdminService.list_audit_logs(session, limit=limit, offset=offset)
    return {"ok": True, "logs": [AuditLogItem.model_validate(log_item) for log_item in logs]}
