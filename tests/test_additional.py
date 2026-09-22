"""تست‌های تکمیلی برای پوشش کامل باگ‌های گزارش Audit و قابلیت‌های جدید."""

import sqlite3
import tempfile

from fastapi.testclient import TestClient

from mas_app.config import Settings
from mas_app.db.migrator import run_database_migrations
from mas_app.db.session import Database


def test_error_envelope_structure(client: TestClient):
    """بررسی ساختار یکدست پاکت خطای فارسی (ok: false, error: {code, message, details})."""
    # ۱. خطای ۴۰۱ بدون لاگین
    res401 = client.get("/api/rooms/999999")
    assert res401.status_code == 401
    data401 = res401.json()
    assert data401["ok"] is False
    assert data401["error"]["code"] == "UNAUTHORIZED"

    # ۲. لاگین و دریافت خطای ۴۰۴ برای منبع ناموجود
    client.post(
        "/api/auth/register",
        json={"username": "envelope_user", "password": "password1234"},
    )
    res404 = client.get("/api/rooms/999999")
    assert res404.status_code == 404
    data404 = res404.json()
    assert data404["ok"] is False
    assert data404["error"]["code"] == "NOT_FOUND"

    # ۳. خطای اعتبارسنجی ورودی (Validation)
    res_val = client.post("/api/auth/login", json={"username": ""})
    assert res_val.status_code == 400
    data_val = res_val.json()
    assert data_val["ok"] is False
    assert data_val["error"]["code"] == "VALIDATION_ERROR"


def test_speaker_reorder(client: TestClient):
    """تغییر ترتیب سخنران‌ها بدون تداخل قید یکتا (Unique constraint)."""
    client.post(
        "/api/auth/register",
        json={"username": "user_reorder", "password": "password1234"},
    )
    res = client.post(
        "/api/rooms",
        json={"name": "اتاق مرتب‌سازی", "capacity": 3},
    )
    room_id = res.json()["room"]["id"]
    speakers = client.get(f"/api/rooms/{room_id}").json()["room"]["speakers"]
    sp_ids = [s["id"] for s in speakers]

    # معکوس کردن ترتیب: [id2, id1, id0]
    reversed_ids = list(reversed(sp_ids))
    res_reorder = client.post(
        f"/api/rooms/{room_id}/speakers/reorder",
        json={"speaker_ids": reversed_ids},
    )
    assert res_reorder.status_code == 200

    new_speakers = client.get(f"/api/rooms/{room_id}").json()["room"]["speakers"]
    assert [s["id"] for s in new_speakers] == reversed_ids
    assert [s["order_index"] for s in new_speakers] == [0, 1, 2]


def test_legacy_database_migration_with_duplicates():
    """شبیه‌سازی یک دیتابیس قدیمی SQLite نسخه ۱ دارای یوزرهای تکراری و ارتقای بدون خطای C-08."""
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp_db:
        # ساخت دستی جدول قدیمی users بدون ستون‌های جدید و با یوزرنیم تکراری
        conn = sqlite3.connect(tmp_db.name)
        c = conn.cursor()
        c.execute(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username VARCHAR(32) NOT NULL,
                password_hash VARCHAR(256) NOT NULL,
                account_name VARCHAR(120) DEFAULT '',
                created_at INTEGER DEFAULT 0
            )
        """
        )
        c.execute(
            """
            CREATE TABLE rooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER,
                name VARCHAR(160) NOT NULL,
                capacity INTEGER NOT NULL,
                created_at INTEGER DEFAULT 0
            )
        """
        )
        c.execute(
            """
            CREATE TABLE room_states (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER,
                current_speaker_id INTEGER,
                elapsed_ms BIGINT DEFAULT 0
            )
        """
        )
        # درج نام کاربری تکراری قدیمی 'ali'
        c.execute("INSERT INTO users (username, password_hash) VALUES ('ali', 'hash1')")
        c.execute("INSERT INTO users (username, password_hash) VALUES ('Ali', 'hash2')")
        conn.commit()
        conn.close()

        # اجرای مایگریشن بر روی دیتابیس قدیمی
        settings = Settings(
            env="test",
            database_url=f"sqlite:///{tmp_db.name}",
            secret_key="a" * 40,
            storage_backend="local",
        )
        db = Database(settings)
        run_database_migrations(db, settings)

        # بررسی اینکه دیتابیس بدون خطا ارتقا یافته و نام‌های تکراری تفکیک شده‌اند
        with db.session() as s:
            from sqlalchemy import text

            rows = s.execute(text("SELECT id, username, username_key FROM users ORDER BY id")).fetchall()
            assert len(rows) == 2
            assert rows[0][2] != rows[1][2]  # username_key نباید یکسان باشد
