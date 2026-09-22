"""اسکیماهای نشست ضبط تکه‌ای."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class RecordingSessionStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: int
    room_id: int
    speaker_id: int | None = None
    speaker_name: str
    status: str  # recording | paused | finalizing | saved | discarded | failed
    chunk_seq: int
    bytes_received: int
    recorded_ms: int
    active: bool


class RecordingChunkResponse(BaseModel):
    session_id: int
    seq: int
    bytes_received: int
    status: str


class RecordingFinishRequest(BaseModel):
    save: bool = True
