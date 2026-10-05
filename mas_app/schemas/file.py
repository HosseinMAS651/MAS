"""اسکیماهای فایل‌ها و ضبط‌ها."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class FileReviewRequest(BaseModel):
    approved: bool


class FileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    room_id: int
    speaker_id: int | None = None
    filename: str
    content_type: str
    size_bytes: int
    upload_type: str
    approval_status: str = "approved"
    duration_ms: int | None = None
    speaker_name: str
    created_at_ms: int
