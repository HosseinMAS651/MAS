"""اسکیماهای تایمر و کنترل پخش."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .file import FileResponse
from .speaker import SpeakerResponse

TimerAction = Literal[
    "start",
    "pause",
    "resume",
    "finish",
    "continue_overtime",
    "finish_overtime",
    "reset",
    "goto",
]


class TimerActionRequest(BaseModel):
    action: TimerAction
    speaker_id: int | None = None
    expected_version: int | None = Field(default=None, ge=1)


class TimerStateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    room_id: int
    version: int
    running: bool
    awaiting_decision: bool
    stop_reason: str
    current_index: int
    current_speaker_id: int | None = None
    current_speaker: SpeakerResponse | None = None
    elapsed_ms: int
    remaining_ms: int
    overtime_ms: int
    limit_ms: int
    total_speakers: int
    finished_speakers: int
    speakers: list[SpeakerResponse] = []
    live_files: list[FileResponse] = []
    recording_status: str = "inactive"  # inactive | recording | paused | saving
