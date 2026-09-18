from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    raw = os.getenv(name)
    try:
        value = int(raw) if raw is not None else default
    except ValueError:
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


@dataclass(frozen=True)
class Settings:
    env: str
    secret_key: str
    database_url: str
    storage_dir: Path
    cookie_secure: bool
    session_seconds: int
    max_upload_bytes: int
    max_total_upload_bytes: int
    max_files_per_request: int
    max_room_storage_bytes: int
    max_recording_seconds: int
    login_max_failures: int
    login_window_seconds: int
    register_max_attempts: int
    register_window_seconds: int
    max_password_length: int = 128
    min_password_length: int = 8
    max_username_length: int = 32
    min_username_length: int = 3
    max_room_capacity: int = 100
    min_room_capacity: int = 1


def load_settings() -> Settings:
    env = os.getenv("MAS_ENV", "development").strip().lower()
    secret = os.getenv("MAS_SECRET_KEY", "")
    if len(secret) < 32:
        if env == "production":
            raise RuntimeError("MAS_SECRET_KEY must be at least 32 characters in production.")
        # Development-only deterministic secret; never use this in production.
        secret = f"dev-only-{BASE_DIR}".encode("utf-8").hex().ljust(64, "0")

    database_url = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'mas.db'}")
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)

    storage_dir = Path(os.getenv("MAS_STORAGE_DIR", str(BASE_DIR / "uploads"))).expanduser()
    storage_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        env=env,
        secret_key=secret,
        database_url=database_url,
        storage_dir=storage_dir,
        cookie_secure=env_bool("MAS_COOKIE_SECURE", env == "production"),
        session_seconds=env_int("MAS_SESSION_DAYS", 14, 1, 90) * 86400,
        max_upload_bytes=env_int("MAS_MAX_UPLOAD_MB", 50, 1, 2048) * 1024 * 1024,
        max_total_upload_bytes=env_int("MAS_MAX_TOTAL_UPLOAD_MB", 200, 1, 4096) * 1024 * 1024,
        max_files_per_request=env_int("MAS_MAX_FILES_PER_REQUEST", 100, 1, 1000),
        max_room_storage_bytes=env_int("MAS_MAX_ROOM_STORAGE_MB", 1000, 10, 100000) * 1024 * 1024,
        max_recording_seconds=env_int("MAS_MAX_RECORDING_MINUTES", 180, 1, 24 * 60) * 60,
        login_max_failures=env_int("MAS_LOGIN_MAX_FAILURES", 10, 1, 100),
        login_window_seconds=env_int("MAS_LOGIN_WINDOW_SECONDS", 600, 30, 86400),
        register_max_attempts=env_int("MAS_REGISTER_MAX_ATTEMPTS", 20, 1, 500),
        register_window_seconds=env_int("MAS_REGISTER_WINDOW_SECONDS", 600, 30, 86400),
    )
