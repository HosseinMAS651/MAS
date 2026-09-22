"""اسکیماهای اتاق تماشاگران (عمومی بدون لاگین)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from .file import FileResponse
from .speaker import SpeakerResponse


class PublicRoomStateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    room_name: str
    public_enabled: bool
    running: bool
    awaiting_decision: bool
    current_index: int
    current_speaker: SpeakerResponse | None = None
    elapsed_ms: int
    remaining_ms: int
    overtime_ms: int
    limit_ms: int
    total_speakers: int
    finished_speakers: int
    speakers: list[SpeakerResponse] = []
    live_files: list[FileResponse] = []
