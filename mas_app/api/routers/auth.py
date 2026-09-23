"""مسیریاب احراز هویت و حساب کاربری."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from ...schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    RegisterRequest,
    UpdateProfileRequest,
    UserResponse,
)
from ..deps import (
    get_auth_service,
    get_client_ip,
    get_current_active_user,
    get_db,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register")
def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_db)],
    auth_service: Annotated[object, Depends(get_auth_service)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> dict:
    user_agent = request.headers.get("user-agent", "")
    user = auth_service.register(
        session,
        username=payload.username,
        password=payload.password,
        account_name=payload.account_name,
        age=payload.age,
        job=payload.job,
        timezone=payload.timezone,
        calendar=payload.calendar,
        ip=client_ip,
        user_agent=user_agent,
    )
    # لاگین خودکار بلافاصله پس از ثبت‌نام
    _, session_token, csrf_token = auth_service.login(
        session,
        username=payload.username,
        password=payload.password,
        ip=client_ip,
        user_agent=user_agent,
    )

    settings = auth_service.settings
    response.set_cookie(
        key=settings.cookie_name,
        value=session_token,
        max_age=settings.session_idle_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
        domain=settings.cookie_domain or None,
    )
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=csrf_token,
        max_age=settings.session_idle_seconds,
        httponly=False,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
        domain=settings.cookie_domain or None,
    )

    return {
        "ok": True,
        "user": UserResponse.model_validate(user),
    }


@router.post("/login")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_db)],
    auth_service: Annotated[object, Depends(get_auth_service)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> dict:
    user_agent = request.headers.get("user-agent", "")
    user, session_token, csrf_token = auth_service.login(
        session,
        username=payload.username,
        password=payload.password,
        ip=client_ip,
        user_agent=user_agent,
    )

    settings = auth_service.settings
    response.set_cookie(
        key=settings.cookie_name,
        value=session_token,
        max_age=settings.session_idle_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
        domain=settings.cookie_domain or None,
    )
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=csrf_token,
        max_age=settings.session_idle_seconds,
        httponly=False,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
        domain=settings.cookie_domain or None,
    )

    return {
        "ok": True,
        "user": UserResponse.model_validate(user),
    }


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_db)],
    auth_service: Annotated[object, Depends(get_auth_service)],
) -> dict:
    token = request.cookies.get(auth_service.settings.cookie_name)
    if token:
        auth_service.logout(session, token)
    response.delete_cookie(key=auth_service.settings.cookie_name, path="/", domain=auth_service.settings.cookie_domain or None)
    response.delete_cookie(key=auth_service.settings.csrf_cookie_name, path="/", domain=auth_service.settings.cookie_domain or None)
    return {"ok": True, "message": "خروج با موفقیت انجام شد."}


@router.get("/me")
def get_current_profile(
    current_user: Annotated[object, Depends(get_current_active_user)],
) -> dict:
    return {"ok": True, "user": UserResponse.model_validate(current_user)}


@router.post("/profile")
def update_profile(
    payload: UpdateProfileRequest,
    current_user: Annotated[object, Depends(get_current_active_user)],
    session: Annotated[Session, Depends(get_db)],
    auth_service: Annotated[object, Depends(get_auth_service)],
) -> dict:
    user = auth_service.update_profile(
        session,
        current_user,
        account_name=payload.account_name,
        age=payload.age,
        job=payload.job,
        timezone=payload.timezone,
        calendar=payload.calendar,
    )
    return {"ok": True, "user": UserResponse.model_validate(user)}


@router.post("/change-password")
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    current_user: Annotated[object, Depends(get_current_active_user)],
    session: Annotated[Session, Depends(get_db)],
    auth_service: Annotated[object, Depends(get_auth_service)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> dict:
    token = request.cookies.get(auth_service.settings.cookie_name, "")
    user_agent = request.headers.get("user-agent", "")
    auth_service.change_password(
        session,
        current_user,
        current_password=payload.current_password,
        new_password=payload.new_password,
        current_session_token=token,
        ip=client_ip,
        user_agent=user_agent,
    )
    return {"ok": True, "message": "رمز عبور با موفقیت تغییر یافت."}
