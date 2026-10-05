from mas_app.services.reaction_service import reaction_manager


def test_pdf_report_and_endpoints(client):
    client.post("/api/auth/register", json={"username": "feat_user", "password": "password1234"})
    res = client.post("/api/rooms", json={
        "name": "اتاق تست فیچرها",
        "capacity": 3,
        "public_enabled": True,
        "live_files_enabled": True,
    })
    assert res.status_code == 200
    room_id = res.json()["room"]["id"]

    # دریافت مشخصات کامل اتاق شامل public_token
    detail_res = client.get(f"/api/rooms/{room_id}")
    assert detail_res.status_code == 200
    room_detail = detail_res.json()["room"]
    public_token = room_detail["public_token"]
    assert public_token is not None

    # 1. تست دانلود PDF گزارش از سمت پنل اتاق
    pdf_res = client.get(f"/api/rooms/{room_id}/report/pdf")
    assert pdf_res.status_code == 200
    assert pdf_res.headers["content-type"] == "application/pdf"
    assert pdf_res.content.startswith(b"%PDF-")

    # 2. تست دانلود PDF گزارش از سمت تماشاگر عمومی
    pub_pdf_res = client.get(f"/api/public/{public_token}/report/pdf")
    assert pub_pdf_res.status_code == 200
    assert pub_pdf_res.headers["content-type"] == "application/pdf"
    assert pub_pdf_res.content.startswith(b"%PDF-")

    # 3. تست ارسال و دریافت واکنش‌های زنده
    send_react = client.post(f"/api/public/{public_token}/reactions", json={"emoji": "heart"})
    assert send_react.status_code == 200
    assert send_react.json()["ok"] is True

    get_react = client.get(f"/api/public/{public_token}/reactions")
    assert get_react.status_code == 200
    assert len(get_react.json()["reactions"]) >= 1

    # 4. تست تاگل واکنش‌ها از سمت مجری
    toggle_res = client.post(f"/api/rooms/{room_id}/reactions/toggle")
    assert toggle_res.status_code == 200
    assert toggle_res.json()["reactions_enabled"] is False

    # اکنون ارسال واکنش باید مسدود باشد
    blocked_react = client.post(f"/api/public/{public_token}/reactions", json={"emoji": "clap"})
    assert blocked_react.status_code == 403


def test_public_reaction_posts_are_rate_limited(client):
    client.post("/api/auth/register", json={"username": "reaction_rate_user", "password": "password1234"})
    created = client.post(
        "/api/rooms",
        json={"name": "واکنش محدود", "capacity": 1, "public_enabled": True},
    )
    assert created.status_code == 200
    room_id = created.json()["room"]["id"]
    public_token = client.get(f"/api/rooms/{room_id}").json()["room"]["public_token"]
    reaction_manager.set_enabled(room_id, True)
    client.app.state.settings.reaction_max_per_minute = 2

    first = client.post(f"/api/public/{public_token}/reactions", json={"emoji": "heart"})
    second = client.post(f"/api/public/{public_token}/reactions", json={"emoji": "clap"})
    third = client.post(f"/api/public/{public_token}/reactions", json={"emoji": "fire"})
    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert third.json()["error"]["code"] == "RATE_LIMITED"


def test_reaction_manager_flow():
    room_id = 999
    reaction_manager.set_enabled(room_id, True)
    assert reaction_manager.is_enabled(room_id) is True

    item1 = reaction_manager.add_reaction(room_id, "heart")
    assert item1 is not None
    assert item1.emoji == "heart"

    item2 = reaction_manager.add_reaction(room_id, "fire")
    assert item2 is not None

    recent = reaction_manager.get_recent(room_id, since_seconds=5.0)
    assert len(recent) == 2

    totals = reaction_manager.get_totals(room_id)
    assert totals.get("heart") == 1
    assert totals.get("fire") == 1

    reaction_manager.set_enabled(room_id, False)
    assert reaction_manager.add_reaction(room_id, "clap") is None
