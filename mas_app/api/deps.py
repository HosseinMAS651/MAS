"""وابستگی‌های FastAPI برای دیتابیس، سرویس‌ها، احراز هویت و CSRF."""

from __future__ import annotations

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..core.errors import ForbiddenError, UnauthorizedError
from ..core.security import SecurityManager
from ..db.models import AuthSession, User
from ..db.session import Database
from ..services.auth_service import AuthService
from ..services.cleanup_service import CleanupService
from ..services.recording_service import RecordingService
from ..services.room_service import RoomService
from ..services.speaker_service import SpeakerService
from ..services.timer_service import TimerService
from ..storage.base import StorageBackend
from ..storage.factory import create_storage


def get_app_settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    return settings if settings is not None else get_settings()


def get_app_database(request: Request) -> Database:
    return request.app.state.database


def get_db(database: Annotated[Database, Depends(get_app_database)]) -> Generator[Session, None, None]:
    with database.session() as session:
        yield session


def get_security_manager(settings: Annotated[Settings, Depends(get_app_settings)]) -> SecurityManager:
    return SecurityManager(settings)


def get_storage_backend(settings: Annotated[Settings, Depends(get_app_settings)]) -> StorageBackend:
    return create_storage(settings)


def get_client_ip(
    request: Request,
    security: Annotated[SecurityManager, Depends(get_security_manager)],
) -> str:
    peer_ip = request.client.host if request.client else "127.0.0.1"
    return security.extract_client_ip(dict(request.headers), peer_ip)


def get_auth_service(
    settings: Annotated[Settings, Depends(get_app_settings)],
    security: Annotated[SecurityManager, Depends(get_security_manager)],
) -> AuthService:
    return AuthService(settings, security)


def get_recording_service(
    settings: Annotated[Settings, Depends(get_app_settings)],
    storage: Annotated[StorageBackend, Depends(get_storage_backend)],
) -> RecordingService:
    # No monkey-patch: the same concrete service and signature is visible to FastAPI everywhere.
    return RecordingService(settings, storage)


def get_timer_service(
    recording_service: Annotated[RecordingService, Depends(get_recording_service)],
) -> TimerService:
    return TimerService(recording_service)


def get_room_service(
    settings: Annotated[Settings, Depends(get_app_settings)],
    storage: Annotated[StorageBackend, Depends(get_storage_backend)],
    security: Annotated[SecurityManager, Depends(get_security_manager)],
) -> RoomService:
    return RoomService(settings, storage, security)


def get_speaker_service() -> SpeakerService:
    return SpeakerService()


def get_cleanup_service(
    settings: Annotated[Settings, Depends(get_app_settings)],
    storage: Annotated[StorageBackend, Depends(get_storage_backend)],
) -> CleanupService:
    return CleanupService(settings, storage)


def get_current_user(
    request: Request,
    session: Annotated[Session, Depends(get_db)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    authorization: Annotated[str | None, Header()] = None,
) -> tuple[User, AuthSession]:
    """استخراج کاربر از کوکی HttpOnly یا هدر Bearer."""
    token = request.cookies.get(auth_service.settings.cookie_name)
    if not token and authorization and authorization.startswith("Bearer "):
        token = authorization[7:].strip()
    if not token:
        raise UnauthorizedError("لطفاً ابتدا وارد حساب کاربری خود شوید.")
    return auth_service.get_user_from_token(session, token, touch=True)


def get_current_active_user(
    user_and_session: Annotated[tuple[User, AuthSession], Depends(get_current_user)],
) -> User:
    user, _ = user_and_session
    if not user.is_active:
        raise UnauthorizedError("حساب کاربری شما غیرفعال شده است.")
    return user


def get_current_admin(user: Annotated[User, Depends(get_current_active_user)]) -> User:
    if user.role != "admin":
        raise ForbiddenError("دسترسی به این بخش نیازمند سطح کاربری مدیر (Admin) است.")
    return user
