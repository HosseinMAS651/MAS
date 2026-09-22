"""تست‌های پنل ادمین و لاگ‌های ممیزی (رفع باگ SEC-10)."""

from fastapi.testclient import TestClient


def test_admin_stats_and_audit_logs(client: TestClient):
    # اولین کاربر ثبت‌نام‌شده خودکار نقش admin می‌گیرد
    res_reg = client.post(
        "/api/auth/register",
        json={"username": "super_admin", "password": "adminPassword123!"},
    )
    assert res_reg.status_code == 200
    assert res_reg.json()["user"]["role"] == "admin"

    # ساخت یک اتاق
    client.post(
        "/api/rooms",
        json={"name": "اتاق نمونه مدیر", "capacity": 3},
    )

    # دریافت آمار سیستم
    res_stats = client.get("/api/admin/stats")
    assert res_stats.status_code == 200
    stats = res_stats.json()["stats"]
    assert stats["users_count"] >= 1
    assert stats["rooms_count"] >= 1

    # دریافت لاگ‌های امنیتی و ممیزی (SEC-10)
    res_logs = client.get("/api/admin/audit-logs")
    assert res_logs.status_code == 200
    logs = res_logs.json()["logs"]
    assert len(logs) > 0
    actions = [log_item["action"] for log_item in logs]
    assert "user_registered" in actions
    assert "room_created" in actions
