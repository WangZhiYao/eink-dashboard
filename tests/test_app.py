from datetime import datetime, date
from zoneinfo import ZoneInfo
from fastapi.testclient import TestClient
import app
import render


def test_render_tick_renders_inside_workday_window(monkeypatch):
    calls = []
    monkeypatch.setattr(render, "render_now", lambda: calls.append("full"))
    tz = ZoneInfo("Asia/Shanghai")
    render.render_tick(datetime(2026, 8, 3, 9, 0, tzinfo=tz))    # Monday 9:00
    assert calls == ["full"]
    calls.clear()
    render.render_tick(datetime(2026, 8, 3, 20, 55, tzinfo=tz))  # Monday 20:55
    assert calls == ["full"]
    calls.clear()
    render.render_tick(datetime(2026, 8, 3, 21, 0, tzinfo=tz))   # window closed
    assert calls == []


def test_render_tick_prerender_before_window(monkeypatch):
    calls = []
    monkeypatch.setattr(render, "render_now", lambda: calls.append("full"))
    tz = ZoneInfo("Asia/Shanghai")
    render.render_tick(datetime(2026, 8, 3, 8, 55, tzinfo=tz))    # lookahead
    assert calls == ["full"]
    calls.clear()
    render.render_tick(datetime(2026, 8, 3, 8, 30, tzinfo=tz))    # too early
    assert calls == []


def test_render_tick_rest_day_renders_every_tick_after_render_at(monkeypatch):
    # 休息日从 render_at 起每 5 分钟照常渲染（时钟/天气/待办实时刷新），同工作日布局；
    # render_at 之前不渲染
    calls = []
    monkeypatch.setattr(render, "render_now", lambda: calls.append("full"))
    tz = ZoneInfo("Asia/Shanghai")
    render.render_tick(datetime(2026, 8, 2, 8, 55, tzinfo=tz))    # Sunday before 9:00
    assert calls == []
    render.render_tick(datetime(2026, 8, 2, 9, 0, tzinfo=tz))     # 9:00 (render_at)
    render.render_tick(datetime(2026, 8, 2, 9, 5, tzinfo=tz))     # 9:05 — every tick re-renders
    render.render_tick(datetime(2026, 8, 2, 12, 0, tzinfo=tz))    # 12:00 — same day, still renders
    assert calls == ["full", "full", "full"]


def test_render_tick_holiday_override_renders_full_screen(monkeypatch):
    # override 使工作日变成 rest 日 → render_tick 渲染完整主画面（非独立休息画面），
    # 且同休息日一样每 5 分钟持续渲染
    monkeypatch.setattr(render.calendar, "_overrides",
                        {date(2026, 10, 1): ("rest", "国庆节")})
    calls = []
    monkeypatch.setattr(render, "render_now", lambda: calls.append("full"))
    tz = ZoneInfo("Asia/Shanghai")
    render.render_tick(datetime(2026, 10, 1, 9, 0, tzinfo=tz))
    render.render_tick(datetime(2026, 10, 1, 9, 5, tzinfo=tz))
    assert calls == ["full", "full"]


def test_dashboard_png_served_with_cache_header(tmp_path, monkeypatch):
    # point output at a tmp file we control
    monkeypatch.setattr(app, "OUT", str(tmp_path / "dashboard.png"))
    (tmp_path / "dashboard.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    # don't start the scheduler for the test
    monkeypatch.setattr(app, "_start_scheduler", lambda: None)
    client = TestClient(app.app)
    r = client.get("/dashboard.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.headers["cache-control"] == "public, max-age=300"


def test_health(monkeypatch):
    monkeypatch.setattr(app, "_start_scheduler", lambda: None)  # avoid real render during lifespan
    client = TestClient(app.app)
    r = client.get("/healthz")
    assert r.status_code == 200


def test_todos_page_requires_auth(monkeypatch):
    monkeypatch.setattr(app, "_start_scheduler", lambda: None)   # also skips init_db (it's inside)
    client = TestClient(app.app)
    assert client.get("/todos").status_code == 401
    import base64
    from config import settings
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "secret")
    cred = base64.b64encode(b"admin:secret").decode()
    r = client.get("/todos", headers={"Authorization": f"Basic {cred}"})
    assert r.status_code == 200 and "<title>待办管理" in r.text
