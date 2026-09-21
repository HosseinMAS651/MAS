from __future__ import annotations

import mimetypes
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from fastapi import UploadFile

from .config import Settings

ALLOWED_EXTENSIONS = {
    ".pdf", ".ppt", ".pptx", ".doc", ".docx", ".txt",
    ".mp3", ".wav", ".m4a", ".ogg", ".mp4", ".webm",
    ".png", ".jpg", ".jpeg",
}
RECORDING_EXTENSIONS = {".webm", ".ogg", ".mp4", ".m4a", ".wav", ".mp3"}
DANGEROUS_CONTENT_TYPES = {"text/html", "application/xhtml+xml", "application/javascript", "text/javascript"}


@dataclass(frozen=True)
class StoredUpload:
    original_name: str
    storage_name: str
    size_bytes: int
    content_type: str


def safe_filename(name: str, allowed_extensions: set[str] | None = None) -> str:
    name = Path(name or "").name.replace("\x00", "").strip()
    if not name or name in {".", ".."}:
        raise ValueError("نام فایل نامعتبر است.")
    if len(name) > 255:
        stem, suffix = Path(name).stem, Path(name).suffix
        name = stem[: max(1, 255 - len(suffix))] + suffix
    ext = Path(name).suffix.lower()
    allowed = allowed_extensions or ALLOWED_EXTENSIONS
    if ext not in allowed:
        raise ValueError("این نوع فایل مجاز نیست.")
    return name


def content_type_for(upload: UploadFile, original_name: str) -> str:
    guessed = mimetypes.guess_type(original_name)[0] or "application/octet-stream"
    supplied = (upload.content_type or "").split(";", 1)[0].strip().lower()
    if supplied in DANGEROUS_CONTENT_TYPES:
        return "application/octet-stream"
    return guessed if guessed != "application/octet-stream" else (supplied or guessed)


def validate_recording_type(upload: UploadFile) -> str:
    original = safe_filename(upload.filename or "", RECORDING_EXTENSIONS)
    ext = Path(original).suffix.lower()
    supplied = (upload.content_type or "").split(";", 1)[0].strip().lower()
    allowed_by_ext = {
        ".webm": {"audio/webm"},
        ".ogg": {"audio/ogg", "application/ogg"},
        ".mp4": {"audio/mp4"},
        ".m4a": {"audio/mp4"},
        ".wav": {"audio/wav", "audio/x-wav"},
        ".mp3": {"audio/mpeg"},
    }
    # Some clients omit a Content-Type; extension validation still applies.
    if supplied and supplied not in allowed_by_ext[ext]:
        raise ValueError("فرمت فایل ضبط‌شده با نوع واقعی اعلام‌شده سازگار نیست.")
    return original


async def store_upload(
    upload: UploadFile,
    settings: Settings,
    *,
    request_bytes_used: int = 0,
    allowed_extensions: set[str] | None = None,
    max_bytes: int | None = None,
) -> StoredUpload:
    original = safe_filename(upload.filename or "", allowed_extensions)
    ext = Path(original).suffix.lower()
    storage_name = f"{uuid.uuid4().hex}{ext}"
    tmp = settings.storage_dir / f".upload-{uuid.uuid4().hex}.tmp"
    target = settings.storage_dir / storage_name
    limit = max_bytes or settings.max_upload_bytes
    total = 0
    try:
        with tmp.open("xb") as out:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise ValueError(f"حجم هر فایل حداکثر {limit // 1024 // 1024} مگابایت است.")
                if request_bytes_used + total > settings.max_total_upload_bytes:
                    raise ValueError(f"مجموع فایل‌های این درخواست حداکثر {settings.max_total_upload_bytes // 1024 // 1024} مگابایت است.")
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        if total == 0:
            raise ValueError("فایل خالی قابل ذخیره نیست.")
        os.replace(tmp, target)
        return StoredUpload(original_name=original, storage_name=storage_name, size_bytes=total, content_type=content_type_for(upload, original))
    except Exception:
        tmp.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()


def safe_storage_path(settings: Settings, storage_name: str) -> Path:
    raw = str(storage_name or "")
    if not raw or Path(raw).name != raw or raw in {".", ".."} or "\x00" in raw:
        raise ValueError("مسیر فایل نامعتبر است.")
    candidate = (settings.storage_dir / raw).resolve()
    root = settings.storage_dir.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("مسیر فایل نامعتبر است.")
    return candidate


def content_disposition(filename: str, disposition: str = "attachment") -> str:
    clean = filename.replace("\r", "").replace("\n", "").replace('"', "'")
    return f"{disposition}; filename*=UTF-8''{quote(clean)}"


def cleanup_storage_temp_files(settings: Settings) -> int:
    removed = 0
    for path in settings.storage_dir.glob(".upload-*.tmp"):
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def reconcile_orphans(settings: Settings, referenced: set[str], grace_seconds: int) -> int:
    now = __import__("time").time()
    removed = 0
    for path in settings.storage_dir.iterdir():
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.name in referenced:
            continue
        try:
            age = now - path.stat().st_mtime
        except OSError:
            continue
        if age < grace_seconds:
            continue
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
    return removed
