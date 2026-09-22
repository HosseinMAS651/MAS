"""اسکیماهای احراز هویت و مدیریت کاربر."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core.security import normalize_username


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=128)
    account_name: str = Field(default="", max_length=120)
    age: int | None = Field(default=None, ge=1, le=120)
    job: str = Field(default="", max_length=120)
    timezone: str = Field(default="Asia/Tehran", max_length=64)
    calendar: str = Field(default="jalali")

    @field_validator("username")
    @classmethod
    def _val_user(cls, v: str) -> str:
        clean = normalize_username(v)
        if len(clean) < 3:
            raise ValueError("نام کاربری باید حداقل ۳ کاراکتر باشد.")
        return clean

    @field_validator("calendar")
    @classmethod
    def _val_cal(cls, v: str) -> str:
        if v not in {"jalali", "gregorian"}:
            raise ValueError("تقویم باید 'jalali' یا 'gregorian' باشد.")
        return v


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class UpdateProfileRequest(BaseModel):
    account_name: str = Field(default="", max_length=120)
    age: int | None = Field(default=None, ge=1, le=120)
    job: str = Field(default="", max_length=120)
    timezone: str = Field(default="Asia/Tehran", max_length=64)
    calendar: str = Field(default="jalali")

    @field_validator("calendar")
    @classmethod
    def _val_cal(cls, v: str) -> str:
        if v not in {"jalali", "gregorian"}:
            raise ValueError("تقویم باید 'jalali' یا 'gregorian' باشد.")
        return v


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    account_name: str
    age: int | None = None
    job: str
    role: str
    is_active: bool
    timezone: str
    calendar: str
    storage_used_bytes: int
    created_at_ms: int
