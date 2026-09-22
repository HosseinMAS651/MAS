"""مسیریاب مدیریت اتاق‌ها و فایل‌ها."""

from __future__ import annotations

import urllib.parse
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.errors import NotFoundError, ValidationAppError
from ...db.models import SpeechFile, User
from ...schemas.file import FileResponse
from ...schemas.room import (
    RoomCreateRequest,
    RoomDetailResponse,
    RoomSummaryResponse,
    RoomUpdateRequest,
)
from ...schemas.speaker import SpeakerResponse
from ..deps import (
    get_client_ip,
    get_current_active_user,
    get_db,
    get_room_service,
    get_storage_backend,
)

router = APIRouter(prefix="/api/rooms", tags=["rooms"])


@router.get("")
def list_rooms(
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[Session, Depends(get_db)],
    room_service: Annotated[object, Depends(get_room_service)],
) -> dict:
    rooms = room_service.list_rooms_for_user(session, current_user.id)
    summaries = []
    for r in rooms:
        active_count = sum(1 for s in r.speakers if s.name.strip())
        summary = RoomSummaryResponse(
            id=r.id,
            name=r.name,
            description=r.description,
            capacity=r.capacity,
            recording_enabled=r.recording_enabled,
            live_files_enabled=r.live_files_enabled,
            public_enabled=r.public_enabled,
            timing_mode=r.timing_mode,
            global_seconds=r.global_seconds,
            order_mode=r.order_mode,
            storage_used_bytes=r.storage_used_bytes,
            created_at_ms=r.created_at_ms,
            speaker_count=len(r.speakers),
            active_speaker_count=active_count,
        )
        summaries.append(summary)

    return {"ok": True, "rooms": summaries}


@router.post("")
def create_room(
    payload: RoomCreateRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[Session, Depends(get_db)],
    room_service: Annotated[object, Depends(get_room_service)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> dict:
    room = room_service.create_room(
        session,
        current_user,
        name=payload.name,
        capacity=payload.capacity,
        description=payload.description,
        recording_enabled=payload.recording_enabled,
        live_files_enabled=payload.live_files_enabled,
        timing_mode=payload.timing_mode,
        global_seconds=payload.global_seconds,
        order_mode=payload.order_mode,
        public_enabled=payload.public_enabled,
        ip=client_ip,
    )
    return {
        "ok": True,
        "room": RoomSummaryResponse.model_validate(room),
    }


@router.get("/{room_id}")
def get_room_detail(
    room_id: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[Session, Depends(get_db)],
    room_service: Annotated[object, Depends(get_room_service)],
) -> dict:
    room = room_service.get_room_for_user(session, room_id, current_user)
    speakers = sorted(room.speakers, key=lambda s: s.order_index)

    sp_responses = []
    for s in speakers:
        el = s.timer.elapsed_ms if s.timer else 0
        ot = s.timer.overtime_ms if s.timer else 0
        sp_responses.append(
            SpeakerResponse(
                id=s.id,
                room_id=s.room_id,
                order_index=s.order_index,
                name=s.name,
                gender=s.gender,
                age=s.age,
                description=s.description,
                speaking_seconds=s.speaking_seconds,
                is_finished=s.is_finished,
                finished_at_ms=s.finished_at_ms,
                elapsed_ms=el,
                overtime_ms=ot,
            )
        )

    files = [FileResponse.model_validate(f) for f in room.files if f.upload_type != "recording"]
    recordings = [FileResponse.model_validate(f) for f in room.files if f.upload_type == "recording"]

    active_count = sum(1 for s in speakers if s.name.strip())
    detail = RoomDetailResponse(
        id=room.id,
        name=room.name,
        description=room.description,
        capacity=room.capacity,
        recording_enabled=room.recording_enabled,
        live_files_enabled=room.live_files_enabled,
        public_enabled=room.public_enabled,
        public_token=room.public_token,
        timing_mode=room.timing_mode,
        global_seconds=room.global_seconds,
        order_mode=room.order_mode,
        storage_used_bytes=room.storage_used_bytes,
        created_at_ms=room.created_at_ms,
        speaker_count=len(speakers),
        active_speaker_count=active_count,
        speakers=sp_responses,
        files=files,
        recordings=recordings,
    )
    return {"ok": True, "room": detail}


@router.put("/{room_id}")
def update_room(
    room_id: int,
    payload: RoomUpdateRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[Session, Depends(get_db)],
    room_service: Annotated[object, Depends(get_room_service)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> dict:
    room = room_service.get_room_for_user(session, room_id, current_user)
    updated = room_service.update_room(
        session,
        room,
        name=payload.name,
        capacity=payload.capacity,
        description=payload.description,
        recording_enabled=payload.recording_enabled,
        live_files_enabled=payload.live_files_enabled,
        timing_mode=payload.timing_mode,
        global_seconds=payload.global_seconds,
        order_mode=payload.order_mode,
        public_enabled=payload.public_enabled,
        confirm_shrink=payload.confirm_shrink,
        ip=client_ip,
    )
    return {"ok": True, "room": RoomSummaryResponse.model_validate(updated)}


@router.delete("/{room_id}")
def delete_room(
    room_id: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[Session, Depends(get_db)],
    room_service: Annotated[object, Depends(get_room_service)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> dict:
    room = room_service.get_room_for_user(session, room_id, current_user)
    room_service.delete_room(session, room, current_user, ip=client_ip)
    return {"ok": True, "message": "اتاق و کلیه فایل‌های آن با موفقیت حذف شدند."}


@router.post("/{room_id}/rotate-public-token")
def rotate_public_token(
    room_id: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[Session, Depends(get_db)],
    room_service: Annotated[object, Depends(get_room_service)],
) -> dict:
    room = room_service.get_room_for_user(session, room_id, current_user)
    new_token = room_service.rotate_public_token(session, room)
    return {"ok": True, "public_token": new_token}


@router.get("/{room_id}/qr")
def get_room_qr(
    room_id: int,
    request: Request,
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[Session, Depends(get_db)],
    room_service: Annotated[object, Depends(get_room_service)],
) -> Response:
    room = room_service.get_room_for_user(session, room_id, current_user)
    if not room.public_token:
        raise ValidationAppError("ابتدا دسترسی عمومی اتاق را فعال کنید.")

    base_url = room_service.settings.public_base_url or str(request.base_url).rstrip("/")
    public_url = f"{base_url}/public/{room.public_token}"
    svg_data = room_service.generate_qr_svg(public_url)
    return Response(content=svg_data, media_type="image/svg+xml")


@router.post("/{room_id}/files")
async def upload_file(
    room_id: int,
    file: Annotated[UploadFile, File()],
    upload_type: Annotated[str, Form()] = "common",
    speaker_id: Annotated[int | None, Form()] = None,
    current_user: Annotated[User, Depends(get_current_active_user)] = None,
    session: Annotated[Session, Depends(get_db)] = None,
    room_service: Annotated[object, Depends(get_room_service)] = None,
) -> dict:
    room = room_service.get_room_for_user(session, room_id, current_user)

    async def _file_stream():
        while True:
            chunk = await file.read(65_536)
            if not chunk:
                break
            yield chunk

    speech_file = await room_service.upload_speech_file(
        session,
        room,
        upload_type=upload_type,
        filename=file.filename or "file",
        content_type=file.content_type or "application/octet-stream",
        stream=_file_stream(),
        speaker_id=speaker_id,
    )
    return {"ok": True, "file": FileResponse.model_validate(speech_file)}


@router.delete("/{room_id}/files/{file_id}")
def delete_file(
    room_id: int,
    file_id: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[Session, Depends(get_db)],
    room_service: Annotated[object, Depends(get_room_service)],
) -> dict:
    room = room_service.get_room_for_user(session, room_id, current_user)
    room_service.delete_speech_file(session, room, file_id)
    return {"ok": True, "message": "فایل با موفقیت حذف شد."}


@router.get("/{room_id}/files/{file_id}/download")
async def download_file(
    room_id: int,
    file_id: int,
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[Session, Depends(get_db)],
    room_service: Annotated[object, Depends(get_room_service)],
    storage: Annotated[object, Depends(get_storage_backend)],
) -> Response:
    room = room_service.get_room_for_user(session, room_id, current_user)
    file = session.execute(
        select(SpeechFile).where(SpeechFile.id == file_id, SpeechFile.room_id == room.id)
    ).scalar_one_or_none()
    if not file:
        raise NotFoundError("فایل مورد نظر یافت نشد.")

    # پشتیبانی از Presigned URL برای S3
    presigned = storage.get_presigned_download_url(file.storage_key, file.filename)
    if presigned:
        from fastapi.responses import RedirectResponse

        return RedirectResponse(presigned, status_code=303)

    quoted_filename = urllib.parse.quote(file.filename)
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quoted_filename}",
        "Content-Length": str(file.size_bytes),
    }
    stream = storage.open_stream(file.storage_key)
    return StreamingResponse(stream, media_type=file.content_type, headers=headers)
