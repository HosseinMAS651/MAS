"""Request payloads for public speaker-code sessions."""
from __future__ import annotations

from pydantic import BaseModel, Field


class SpeakerEnterRequest(BaseModel):
    code: str = Field(min_length=1, max_length=16)


class SpeakerHeartbeatRequest(BaseModel):
    microphone_ready: bool = False


class SpeakerRecordingStartRequest(BaseModel):
    mime_type: str = Field(default="audio/webm", max_length=80)


class SpeakerRecordingFinishRequest(BaseModel):
    session_id: int = Field(ge=1)
    save: bool = True
