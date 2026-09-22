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
