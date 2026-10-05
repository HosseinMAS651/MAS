"""تست‌های احراز هویت و امنیت رمز عبور."""

import hashlib

from fastapi.testclient import TestClient


def test_register_and_login(client: TestClient):
    # ۱. ثبت نام کاربر جدید
    res = client.post(
        "/api/auth/register",
        json={
            "username": "ali_rezaei",
            "password": "strongPassword123!",
            "account_name": "علی رضایی",
            "timezone": "Asia/Tehran",
            "calendar": "jalali",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["user"]["username"] == "ali_rezaei"
    assert data["user"]["account_name"] == "علی رضایی"

    # ۲. بررسی ورود با همان رمز
    res_login = client.post(
        "/api/auth/login",
        json={"username": "ali_rezaei", "password": "strongPassword123!"},
    )
    assert res_login.status_code == 200
    assert res_login.json()["ok"] is True

    # ۳. دریافت پروفایل
    res_me = client.get("/api/auth/me")
    assert res_me.status_code == 200
    assert res_me.json()["user"]["username"] == "ali_rezaei"


def test_persian_password_change_c02(client: TestClient):
    """بررسی رفع باگ C-02: امکان تغییر رمز با نویسه‌های فارسی/غیر ASCII بدون بروز ۵۰۰."""
    # ثبت نام با رمز فارسی
    persian_pw = "رمز_عبور_فارسی_۱۲۳۴"
    new_persian_pw = "رمز_جدید_خیلی_امن_۵۶۷۸"

    res = client.post(
        "/api/auth/register",
        json={"username": "persian_user", "password": persian_pw},
    )
    assert res.status_code == 200

    # تغییر رمز به رمز فارسی جدید (در نسخه قدیم منجر به کرش ۵۰۰ در hmac.compare_digest می‌شد)
    res_change = client.post(
        "/api/auth/change-password",
        json={
            "current_password": persian_pw,
            "new_password": new_persian_pw,
        },
    )
    assert res_change.status_code == 200
    assert res_change.json()["ok"] is True

    # بررسی امکان ورود با رمز عبور جدید
    res_login = client.post(
        "/api/auth/login",
        json={"username": "persian_user", "password": new_persian_pw},
    )
    assert res_login.status_code == 200
    assert res_login.json()["ok"] is True


def test_pbkdf2_backward_compatibility(client: TestClient, db_session):
    """بررسی سازگاری عقبرو: امکان ورود حساب‌های قدیمی PBKDF2 و ارتقای خودکار به Argon2id."""
    from mas_app.core.timeutil import utc_now_ms
    from mas_app.db.models import User

    # ایجاد یک کاربر به شیوهٔ نسخه ۱ با هش PBKDF2
    salt = bytes.fromhex("11223344556677889900aabbccddeeff")
    digest = hashlib.pbkdf2_hmac("sha256", b"oldSecretPass123", salt, 310000).hex()
    old_hash = f"pbkdf2_sha256$310000${salt.hex()}${digest}"

    now = utc_now_ms()
    legacy_user = User(
        username="legacy_user",
        username_key="legacyuser",
        password_hash=old_hash,
        account_name="کاربر قدیمی",
        role="user",
        is_active=True,
        created_at_ms=now,
        updated_at_ms=now,
    )
    db_session.add(legacy_user)
    db_session.commit()

    # تلاش برای ورود کاربر قدیمی با همان رمز
    res = client.post(
        "/api/auth/login",
        json={"username": "legacy_user", "password": "oldSecretPass123"},
    )
    assert res.status_code == 200
    assert res.json()["ok"] is True

    # بررسی اینکه هش کاربر در دیتابیس خودکار به Argon2id ارتقا یافته است
    db_session.refresh(legacy_user)
    assert legacy_user.password_hash.startswith("$argon2id$")


def test_failed_logins_persist_and_trigger_rate_limit(client: TestClient):
    registered = client.post(
        "/api/auth/register",
        json={"username": "rate_limit_login_user", "password": "correct-password-123"},
    )
    assert registered.status_code == 200
    client.app.state.settings.login_max_attempts = 2

    first = client.post(
        "/api/auth/login",
        json={"username": "rate_limit_login_user", "password": "wrong-password-1"},
    )
    second = client.post(
        "/api/auth/login",
        json={"username": "rate_limit_login_user", "password": "wrong-password-2"},
    )
    blocked = client.post(
        "/api/auth/login",
        json={"username": "rate_limit_login_user", "password": "wrong-password-3"},
    )
    assert first.status_code == 401
    assert second.status_code == 401
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "RATE_LIMITED"

    from sqlalchemy import select

    from mas_app.db.models import RateLimitBucket, User

    with client.app.state.database.session() as session:
        user = session.execute(
            select(User).where(User.username_key == "ratelimitloginuser")
        ).scalar_one()
        assert user.failed_login_count == 2
        bucket = session.execute(
            select(RateLimitBucket).where(
                RateLimitBucket.bucket_key.like("login:userip:ratelimitloginuser:%")
            )
        ).scalar_one()
        assert bucket.count == 2
        assert bucket.blocked_until_ms > 0


def test_recovery_code_is_one_time_and_invalidates_existing_sessions(client: TestClient):
    password = "original-password-123"
    registered = client.post(
        "/api/auth/register",
        json={"username": "recovery_user", "password": password},
    )
    assert registered.status_code == 200
    recovery_code = registered.json()["recovery_code"]
    assert recovery_code
    assert registered.json()["user"]["has_recovery_code"] is True

    recovered = client.post(
        "/api/auth/recover-password",
        json={
            "username": "recovery_user",
            "recovery_code": recovery_code,
            "new_password": "replacement-password-456",
        },
    )
    assert recovered.status_code == 200
    assert client.get("/api/auth/me").status_code == 401

    reused = client.post(
        "/api/auth/recover-password",
        json={
            "username": "recovery_user",
            "recovery_code": recovery_code,
            "new_password": "another-password-789",
        },
    )
    assert reused.status_code == 401

    old_password_login = client.post(
        "/api/auth/login",
        json={"username": "recovery_user", "password": password},
    )
    assert old_password_login.status_code == 401
    new_password_login = client.post(
        "/api/auth/login",
        json={"username": "recovery_user", "password": "replacement-password-456"},
    )
    assert new_password_login.status_code == 200


def test_logged_in_user_can_rotate_recovery_code(client: TestClient):
    registered = client.post(
        "/api/auth/register",
        json={"username": "recovery_rotate_user", "password": "current-password-123"},
    )
    old_code = registered.json()["recovery_code"]
    refreshed = client.post(
        "/api/auth/recovery-code",
        json={"current_password": "current-password-123"},
    )
    assert refreshed.status_code == 200
    new_code = refreshed.json()["recovery_code"]
    assert new_code != old_code

    old_code_response = client.post(
        "/api/auth/recover-password",
        json={
            "username": "recovery_rotate_user",
            "recovery_code": old_code,
            "new_password": "new-password-123",
        },
    )
    assert old_code_response.status_code == 401
    new_code_response = client.post(
        "/api/auth/recover-password",
        json={
            "username": "recovery_rotate_user",
            "recovery_code": new_code,
            "new_password": "new-password-123",
        },
    )
    assert new_code_response.status_code == 200


def test_duplicate_username_prevention(client: TestClient):
    """جلوگیری از ساخت نام کاربری تکراری با تغییر بزرگی/کوچکی حروف."""
    res1 = client.post(
        "/api/auth/register",
        json={"username": "Mohammad", "password": "password1234"},
    )
    assert res1.status_code == 200

    # ثبت‌نام با حروف کوچک همان نام باید خطای ۴۰۰ بدهد
    res2 = client.post(
        "/api/auth/register",
        json={"username": "mohammad", "password": "password1234"},
    )
    assert res2.status_code == 400
    assert res2.json()["ok"] is False
    assert "قبلاً ثبت شده است" in res2.json()["error"]["message"]
