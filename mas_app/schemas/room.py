"""اسکیماهای اتاق."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core.security import normalize_persian_text
from .file import FileResponse
from .speaker import SpeakerResponse


class RoomCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    capacity: int = Field(default=10, ge=1, le=100)
    description: str = Field(default="", max_length=4000)
    recording_enabled: bool = False
    live_files_enabled: bool = False
    timing_mode: str = Field(default="global")
    global_seconds: int = Field(default=300, ge=10, le=86400)
    order_mode: str = Field(default="manual")
    public_enabled: bool = False

    @field_validator("name", "description")
    @classmethod
    def _norm(cls, v: str) -> str:
        return normalize_persian_text(v or "")

    @field_validator("timing_mode")
    @classmethod
    def _timing(cls, v: str) -> str:
        if v not in {"global", "individual"}:
            raise ValueError("نحوه زمان‌بندی باید 'global' یا 'individual' باشد.")
        return v

    @field_validator("order_mode")
    @classmethod
    def _order(cls, v: str) -> str:
        if v not in {"manual", "alpha", "age"}:
            raise ValueError("نحوه ترتیب باید 'manual'، 'alpha' یا 'age' باشد.")
        return v


class RoomUpdateRequest(RoomCreateRequest):
    public_enabled: bool = False
    #: در صورت کاهش ظرفیت اگر سخنرانی حذف شود، این فلگ باید true باشد
    confirm_shrink: bool = False


class RoomSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    capacity: int
    recording_enabled: bool
    live_files_enabled: bool
    public_enabled: bool
    timing_mode: str
    global_seconds: int
    order_mode: str
    storage_used_bytes: int
    created_at_ms: int
    speaker_count: int = 0
    active_speaker_count: int = 0


class RoomDetailResponse(RoomSummaryResponse):
    public_token: str | None = None
    speakers: list[SpeakerResponse] = []
    files: list[FileResponse] = []
    recordings: list[FileResponse] = []
