from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from fastapi.testclient import TestClient
import app


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


def _day_fire_times(specs, tz, day):
    """All (hour, minute) pairs the given cron specs fire on `day` (local tz)."""
    start = datetime(day.year, day.month, day.day, tzinfo=tz)
    end = start + timedelta(days=1)
    pairs = set()
    for spec in specs:
        _id, hour, minute = spec[:3]
        day_of_week = spec[3] if len(spec) > 3 else None
        trig_kwargs = {"hour": hour, "minute": minute, "timezone": tz}
        if day_of_week is not None:
            trig_kwargs["day_of_week"] = day_of_week
        trig = CronTrigger(**trig_kwargs)
        prev, now = None, start
        while True:
            nxt = trig.get_next_fire_time(prev, now)
            if nxt is None or nxt >= end or (prev is not None and nxt <= prev):
                break
            pairs.add((nxt.hour, nxt.minute))
            prev = now = nxt
    return pairs


def test_schedule_renders_final_image_at_pomodoro_end_then_stops():
    # Regression: 21:00 (pomodoro_end) must render exactly once, then stay silent
    # until the next day's pre-render. Before the fix the last render of the day
    # was 20:55 and 21:00 never fired — render_day's hour field is "9-20" (end-1,
    # inclusive) so hour 21 was out of range.
    tz = ZoneInfo(app.settings.tz)
    pairs = _day_fire_times(app._render_schedule(app.settings), tz, datetime(2026, 8, 5))

    assert (9, 0) in pairs and (20, 55) in pairs      # regular window untouched
    assert (8, 55) in pairs                            # pre-render before the day
    assert (21, 0) in pairs                            # THE FIX: final render at 21:00
    # and then it stops for the night — no further renders until tomorrow's 8:55
    assert (21, 5) not in pairs and (21, 55) not in pairs and (22, 0) not in pairs
    assert (0, 0) not in pairs                         # nothing overnight at all
    ordered = sorted(pairs)
    assert ordered[0] == (8, 55)                       # first render of the day
    assert ordered[-1] == (21, 0)                      # last render of the day


def test_schedule_friday_ends_early():
    # Friday uses pomodoro_end_friday (default 18) instead of pomodoro_end (21).
    # The final render should be at 18:00, not 21:00, and nothing after that.
    tz = ZoneInfo(app.settings.tz)
    # 2026-08-07 is a Friday (Python weekday() == 4)
    pairs = _day_fire_times(app._render_schedule(app.settings), tz, datetime(2026, 8, 7))

    assert (9, 0) in pairs and (8, 55) in pairs          # morning prerender + 9:00
    assert (17, 55) in pairs                              # last regular render before Friday end
    assert (18, 0) in pairs                               # Friday final render at 18:00
    assert (21, 0) not in pairs                           # NOT the Mon-Thu final render
    assert (18, 5) not in pairs and (18, 55) not in pairs # nothing after Friday end
    ordered = sorted(pairs)
    assert ordered[0] == (8, 55)
    assert ordered[-1] == (18, 0)                         # last render of Friday
