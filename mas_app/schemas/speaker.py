"""اسکیماهای سخنران."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core.security import normalize_persian_text


class SpeakerUpdateRequest(BaseModel):
    name: str = Field(default="", max_length=120)
    gender: str = Field(default="")
    age: int | None = Field(default=None, ge=1, le=120)
    description: str = Field(default="", max_length=4000)
    speaking_seconds: int = Field(default=300, ge=10, le=86400)

    @field_validator("name", "description")
    @classmethod
    def _norm(cls, v: str) -> str:
        return normalize_persian_text(v or "")

    @field_validator("gender")
    @classmethod
    def _gender(cls, v: str) -> str:
        clean = (v or "").strip().lower()
        if clean and clean not in {"male", "female", "other"}:
            raise ValueError("جنسیت نامعتبر است.")
        return clean


class SpeakerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    room_id: int
    order_index: int
    name: str
    gender: str
    age: int | None = None
    description: str
    speaking_seconds: int
    is_finished: bool
    finished_at_ms: int
    elapsed_ms: int = 0
    overtime_ms: int = 0


class SpeakerReorderRequest(BaseModel):
    speaker_ids: list[int] = Field(min_length=1)


class SpeakerDeleteRequest(BaseModel):
    #: اگر ضبط فعال باشد، کاربر می‌تواند مشخص کند که آیا فایل ذخیره شود یا دور ریخته شود.
    save_recording: bool | None = None
