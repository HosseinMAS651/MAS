from __future__ import annotations
import mimetypes, os, uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote
from fastapi import UploadFile
from .config import Settings

ALLOWED_EXTENSIONS = {".pdf",".ppt",".pptx",".doc",".docx",".txt",".mp3",".wav",".m4a",".ogg",".mp4",".webm",".png",".jpg",".jpeg"}
DANGEROUS_CONTENT_TYPES = {"text/html","application/xhtml+xml","application/javascript","text/javascript"}

@dataclass(frozen=True)
class StoredUpload:
    original_name: str
    storage_name: str
    size_bytes: int
    content_type: str


def safe_filename(name: str) -> str:
    clean = Path(name or "").name.replace("\x00", "").strip()
    if not clean or clean in {".", ".."}:
        raise ValueError("نام فایل نامعتبر است.")
    if len(clean) > 255:
        suffix = Path(clean).suffix
        clean = Path(clean).stem[: max(1, 255 - len(suffix))] + suffix
    if Path(clean).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValueError("این نوع فایل مجاز نیست.")
    return clean


def content_type_for(upload: UploadFile, original_name: str) -> str:
    guessed = mimetypes.guess_type(original_name)[0] or "application/octet-stream"
    supplied = (upload.content_type or "").split(";",1)[0].strip().lower()
    if supplied in DANGEROUS_CONTENT_TYPES:
        return "application/octet-stream"
    return guessed if guessed != "application/octet-stream" else (supplied or guessed)


async def store_upload(upload: UploadFile, settings: Settings, *, request_bytes_used: int = 0) -> StoredUpload:
    original = safe_filename(upload.filename or "")
    ext = Path(original).suffix.lower()
    storage_name = f"{uuid.uuid4().hex}{ext}"
    tmp = settings.storage_dir / f".upload-{uuid.uuid4().hex}.tmp"
    target = settings.storage_dir / storage_name
    total = 0
    try:
        with tmp.open("xb") as out:
            while True:
                chunk = await upload.read(1024*1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > settings.max_upload_bytes:
                    raise ValueError(f"حجم هر فایل حداکثر {settings.max_upload_bytes // 1024 // 1024} مگابایت است.")
                if request_bytes_used + total > settings.max_total_upload_bytes:
                    raise ValueError(f"مجموع فایل‌های این درخواست حداکثر {settings.max_total_upload_bytes // 1024 // 1024} مگابایت است.")
                out.write(chunk)
            out.flush(); os.fsync(out.fileno())
        if total == 0:
            raise ValueError("فایل خالی قابل ذخیره نیست.")
        os.replace(tmp, target)
        return StoredUpload(original, storage_name, total, content_type_for(upload, original))
    except Exception:
        tmp.unlink(missing_ok=True); target.unlink(missing_ok=True); raise
    finally:
        await upload.close()


def safe_storage_path(settings: Settings, storage_name: str) -> Path:
    raw = str(storage_name or "")
    if not raw or Path(raw).name != raw or raw in {".",".."} or "\x00" in raw:
        raise ValueError("مسیر فایل نامعتبر است.")
    root = settings.storage_dir.resolve(); candidate = (root / raw).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("مسیر فایل نامعتبر است.")
    return candidate


def content_disposition(filename: str, disposition: str = "attachment") -> str:
    clean = filename.replace("\r","").replace("\n","").replace('"', "'")
    return f"{disposition}; filename*=UTF-8''{quote(clean)}"
