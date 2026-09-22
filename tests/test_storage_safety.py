"""تست‌های ایمنی ذخیره‌سازی و رفع باگ C-06."""

import io

from fastapi.testclient import TestClient


def test_file_upload_and_quota(client: TestClient):
    client.post(
        "/api/auth/register",
        json={"username": "storage_tester", "password": "password1234"},
    )
    res_r = client.post(
        "/api/rooms",
        json={"name": "اتاق فایل", "capacity": 2},
    )
    room_id = res_r.json()["room"]["id"]

    # آپلود یک فایل معتبر PDF
    pdf_content = b"%PDF-1.4 sample content"
    res_up = client.post(
        f"/api/rooms/{room_id}/files",
        data={"upload_type": "common"},
        files={"file": ("presentation.pdf", io.BytesIO(pdf_content), "application/pdf")},
    )
    assert res_up.status_code == 200
    file_id = res_up.json()["file"]["id"]
    assert res_up.json()["file"]["filename"] == "presentation.pdf"

    # دانلود فایل و بررسی محتوا
    res_down = client.get(f"/api/rooms/{room_id}/files/{file_id}/download")
    assert res_down.status_code == 200
    assert res_down.content == pdf_content

    # تلاش برای آپلود فرمت غیرمجاز (مانند .exe)
    res_bad = client.post(
        f"/api/rooms/{room_id}/files",
        data={"upload_type": "common"},
        files={"file": ("malware.exe", io.BytesIO(b"binary"), "application/x-msdownload")},
    )
    assert res_bad.status_code == 400
    assert "فرمت فایل مجاز نیست" in res_bad.json()["error"]["message"]
