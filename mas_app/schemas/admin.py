"""اسکیماهای داشبورد ادمین."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class AdminStatsResponse(BaseModel):
    users_count: int
    rooms_count: int
    recordings_count: int
    total_storage_bytes: int


class AdminUserItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    account_name: str
    role: str
    is_active: bool
    rooms_count: int = 0
    storage_used_bytes: int
    created_at_ms: int
    last_login_at_ms: int


class AdminRoomItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    owner_username: str
    name: str
    capacity: int
    speakers_count: int
    storage_used_bytes: int
    created_at_ms: int


class AuditLogItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_username: str
    action: str
    severity: str
    target_type: str
    target_id: str
    detail: str
    ip: str
    created_at_ms: int
