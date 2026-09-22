"""سرویس احراز هویت و کاربران."""

from __future__ import annotations

import logging

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..core.errors import (
    UnauthorizedError,
    ValidationAppError,
)
from ..core.security import (
    SecurityManager,
    normalize_persian_text,
    normalize_username,
    username_to_key,
)
from ..core.timeutil import utc_now_ms
from ..db.models import AuthSession, User
from .audit import log_event
from .rate_limiter import RateLimiter

logger = logging.getLogger("mas.auth")


class AuthService:
    def __init__(self, settings: Settings, security: SecurityManager) -> None:
        self.settings = settings
        self.security = security

    def register(
        self,
        session: Session,
        *,
        username: str,
        password: str,
        account_name: str = "",
        age: int | None = None,
        job: str = "",
        timezone: str = "Asia/Tehran",
        calendar: str = "jalali",
        ip: str = "",
        user_agent: str = "",
    ) -> User:
        # بررسی سقف ثبت‌نام بر اساس IP
        if ip:
            RateLimiter.check_and_increment(
                session,
                f"register:ip:{ip}",
                action="register",
                max_attempts=self.settings.register_max_per_ip,
                window_seconds=self.settings.register_window_seconds,
            )

        u_key = username_to_key(username)
        existing = session.execute(
            select(User).where(User.username_key == u_key)
        ).scalar_one_or_none()
        if existing:
            raise ValidationAppError("این نام کاربری قبلاً ثبت شده است.")

        # تعیین نقش (اگر نام کاربری با bootstrap admin مطابقت داشت نقش ادمین می‌گیرد)
        role = "user"
        if self.settings.bootstrap_admin_username and u_key == username_to_key(
            self.settings.bootstrap_admin_username
        ):
            role = "admin"

        # بررسی اینکه آیا اولین کاربر سیستم است (اولین کاربر خودکار ادمین شود)
        total_users = session.execute(select(func.count(User.id))).scalar() or 0
        if total_users == 0:
            role = "admin"

        pwd_hash = self.security.hash_password(password)
        now_ms = utc_now_ms()

        user = User(
            username=normalize_username(username),
            username_key=u_key,
            password_hash=pwd_hash,
            account_name=normalize_persian_text(account_name),
            age=age,
            job=normalize_persian_text(job),
            role=role,
            is_active=True,
            timezone=timezone or "Asia/Tehran",
            calendar=calendar or "jalali",
            storage_used_bytes=0,
            created_at_ms=now_ms,
            updated_at_ms=now_ms,
            last_login_at_ms=now_ms,
        )
        session.add(user)
        session.flush()

        log_event(
            session,
            action="user_registered",
            actor_user_id=user.id,
            actor_username=user.username,
            target_type="user",
            target_id=str(user.id),
            detail={"role": role, "username": user.username},
            ip=ip,
            user_agent=user_agent,
        )
        return user

    def login(
        self,
        session: Session,
        *,
        username: str,
        password: str,
        ip: str = "",
        user_agent: str = "",
    ) -> tuple[User, str, str]:
        """ورود کاربر.

        خروجی:
            (کاربر, توکن خام نشست, توکن خام CSRF)
        """
        u_key = username_to_key(username)

        # کنترل Rate Limit بر اساس IP و Username
        if ip:
            RateLimiter.check_and_increment(
                session,
                f"login:ip:{ip}",
                action="login",
                max_attempts=self.settings.login_max_attempts * 3,
                window_seconds=self.settings.login_window_seconds,
            )
        RateLimiter.check_and_increment(
            session,
            f"login:user:{u_key}",
            action="login",
            max_attempts=self.settings.login_max_attempts,
            window_seconds=self.settings.login_window_seconds,
        )

        user = session.execute(
            select(User).where(User.username_key == u_key)
        ).scalar_one_or_none()
        if not user or not user.is_active:
            raise UnauthorizedError("نام کاربری یا رمز عبور اشتباه است.")

        valid, needs_rehash = self.security.verify_password(password, user.password_hash)
        if not valid:
            user.failed_login_count += 1
            session.flush()
            log_event(
                session,
                action="login_failed",
                actor_user_id=user.id,
                actor_username=user.username,
                severity="warning",
                target_type="user",
                target_id=str(user.id),
                detail={"reason": "invalid_password"},
                ip=ip,
                user_agent=user_agent,
            )
            raise UnauthorizedError("نام کاربری یا رمز عبور اشتباه است.")

        # اگر رمز معتبر بود، در صورت نیاز به روز رسانی خودکار به Argon2id (مهاجرت بدون دردسر)
        if needs_rehash:
            user.password_hash = self.security.hash_password(password)

        user.failed_login_count = 0
        now_ms = utc_now_ms()
        user.last_login_at_ms = now_ms

        # ریست کردن باکت‌های تلاش ناموفق
        if ip:
            RateLimiter.reset(session, f"login:ip:{ip}")
        RateLimiter.reset(session, f"login:user:{u_key}")

        # ساخت توکن نشست و CSRF
        raw_session_token = self.security.generate_session_token()
        session_token_hash = self.security.hash_token(raw_session_token)

        raw_csrf_token = self.security.generate_csrf_token()
        csrf_hash = self.security.hash_token(raw_csrf_token)

        expires_at_ms = now_ms + (self.settings.session_idle_seconds * 1000)

        auth_session = AuthSession(
            user_id=user.id,
            token_hash=session_token_hash,
            csrf_hash=csrf_hash,
            created_at_ms=now_ms,
            expires_at_ms=expires_at_ms,
            last_seen_at_ms=now_ms,
            ip=ip[:64],
            user_agent=user_agent[:255],
        )
        session.add(auth_session)
        session.flush()

        log_event(
            session,
            action="login_success",
            actor_user_id=user.id,
            actor_username=user.username,
            target_type="user",
            target_id=str(user.id),
            detail={"upgraded_hash": needs_rehash},
            ip=ip,
            user_agent=user_agent,
        )
        return user, raw_session_token, raw_csrf_token

    def get_user_from_token(
        self, session: Session, raw_token: str, *, touch: bool = True
    ) -> tuple[User, AuthSession]:
        if not raw_token:
            raise UnauthorizedError("توکن نشست ارائه نشده است.")

        token_hash = self.security.hash_token(raw_token)
        auth_session = session.execute(
            select(AuthSession).where(AuthSession.token_hash == token_hash)
        ).scalar_one_or_none()
        if not auth_session:
            raise UnauthorizedError("نشست نامعتبر است یا منقضی شده است.")

        now_ms = utc_now_ms()
        # بررسی انقضای زمانی شناور (Idle)
        if auth_session.expires_at_ms < now_ms:
            session.delete(auth_session)
            session.flush()
            raise UnauthorizedError("نشست شما به دلیل عدم فعالیت منقضی شده است.")

        # بررسی انقضای مطلق
        max_lifetime_ms = self.settings.session_absolute_seconds * 1000
        if (now_ms - auth_session.created_at_ms) > max_lifetime_ms:
            session.delete(auth_session)
            session.flush()
            raise UnauthorizedError("نشست شما به حداکثر طول مجاز رسیده است. لطفاً دوباره وارد شوید.")

        user = session.execute(
            select(User).where(User.id == auth_session.user_id)
        ).scalar_one_or_none()
        if not user or not user.is_active:
            session.delete(auth_session)
            session.flush()
            raise UnauthorizedError("حساب کاربری فعال نیست.")

        if touch:
            auth_session.last_seen_at_ms = now_ms
            auth_session.expires_at_ms = now_ms + (self.settings.session_idle_seconds * 1000)
            session.flush()

        return user, auth_session

    def logout(self, session: Session, raw_token: str) -> None:
        if not raw_token:
            return
        token_hash = self.security.hash_token(raw_token)
        session.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash))
        session.flush()

    def change_password(
        self,
        session: Session,
        user: User,
        *,
        current_password: str,
        new_password: str,
        current_session_token: str = "",
        ip: str = "",
        user_agent: str = "",
    ) -> None:
        # بررسی رمز فعلی
        valid, _ = self.security.verify_password(current_password, user.password_hash)
        if not valid:
            raise ValidationAppError("رمز عبور فعلی نادرست است.")

        # جلوگیری از خطای C-02 (مقایسه ایمن رمز جدید و قدیم)
        if current_password == new_password:
            raise ValidationAppError("رمز عبور جدید نمی‌تواند با رمز عبور فعلی یکسان باشد.")

        user.password_hash = self.security.hash_password(new_password)
        user.updated_at_ms = utc_now_ms()

        # باطل کردن همهٔ نشست‌های دیگر به جز نشست فعلی
        if current_session_token:
            current_hash = self.security.hash_token(current_session_token)
            session.execute(
                delete(AuthSession).where(
                    AuthSession.user_id == user.id,
                    AuthSession.token_hash != current_hash,
                )
            )
        else:
            session.execute(delete(AuthSession).where(AuthSession.user_id == user.id))

        session.flush()
        log_event(
            session,
            action="password_changed",
            actor_user_id=user.id,
            actor_username=user.username,
            severity="warning",
            target_type="user",
            target_id=str(user.id),
            detail={"sessions_invalidated": True},
            ip=ip,
            user_agent=user_agent,
        )

    def update_profile(
        self,
        session: Session,
        user: User,
        *,
        account_name: str,
        age: int | None,
        job: str,
        timezone: str,
        calendar: str,
    ) -> User:
        user.account_name = normalize_persian_text(account_name)
        user.age = age
        user.job = normalize_persian_text(job)
        if timezone:
            user.timezone = timezone
        if calendar in {"jalali", "gregorian"}:
            user.calendar = calendar
        user.profile_completed = True
        user.updated_at_ms = utc_now_ms()
        session.flush()
        return user
