from datetime import datetime
from zoneinfo import ZoneInfo
import render
from fetchers.sht40 import Sht40Data
from fetchers.weather import WeatherData


def test_build_context_assembles_fields(monkeypatch):
    monkeypatch.setattr(render.sht40, "fetch_sht40",
                        lambda *a, **k: Sht40Data(temp=26.0, humidity=42.0, battery=87))
    monkeypatch.setattr(render.weather, "fetch_weather",
                        lambda *a, **k: WeatherData(current={"temp": 28, "text": "多云", "icon": "104"}, hi=29, lo=21, aqi=45))
    render._weather_cache.clear()
    from todos.db import Todo
    monkeypatch.setattr(render, "_todos_for_dashboard", lambda: [Todo(1, "回复邮件", False, "high", "2026-08-03T00:00:00+00:00")])
    ctx = render.build_context(now=datetime(2026, 8, 2, 9, 41))
    assert ctx["time_str"] == "09:41"
    assert ctx["date_str"] == "2026.08.02"
    assert ctx["weekday"] == "星期日"
    assert ctx["indoor"].temp == 26.0
    assert ctx["weather"].hi == 29
    assert ctx["pomodoro"] == {"active": True, "phase": "work", "remaining": 14}
    assert ctx["lunar"] == "六月二十"
    assert ctx["todos"][0].title == "回复邮件"


import os
import asyncio
import threading
import time
import pytest
from PIL import Image

def test_render_to_png_produces_800x480(tmp_path, monkeypatch):
    # stub context so no network
    monkeypatch.setattr(render, "build_context", lambda: {
        "time_str": "09:41", "date_str": "2026.08.02", "weekday": "星期日",
        "indoor": render.sht40.Sht40Data(temp=26.0, humidity=42.0, battery=87),
        "weather": render.weather.WeatherData(current={"temp": 28, "text": "多云", "icon": "104"}, hi=29, lo=21, aqi=45,
                                               hourly=[{"label": "现在", "text": "多云", "temp": 28, "rain": 34}],
                                               sunrise="05:42", sunset="19:08"),
        "lunar": "六月二十",
        "pomodoro": {"active": True, "phase": "work", "remaining": 20},
        "todos": [],
    })
    out = tmp_path / "out.png"
    render.render_to_png(render.build_context(), str(out))
    assert os.path.exists(out)
    with Image.open(out) as im:
        assert im.size == (800, 480)


def test_render_to_png_works_inside_running_event_loop(tmp_path, monkeypatch):
    # Regression: render_to_png must be synchronous (no asyncio.run inside),
    # so it works when called from FastAPI's running event loop (lifespan).
    monkeypatch.setattr(render, "build_context", lambda: {
        "time_str": "09:41", "date_str": "2026.08.02", "weekday": "星期日",
        "indoor": render.sht40.Sht40Data(temp=26.0, humidity=42.0, battery=87),
        "weather": render.weather.WeatherData(current={"temp": 28, "text": "多云", "icon": "104"}, hi=29, lo=21, aqi=45,
                                               hourly=[{"label": "现在", "text": "多云", "temp": 28, "rain": 34}],
                                               sunrise="05:42", sunset="19:08"),
        "lunar": "六月二十",
        "pomodoro": {"active": True, "phase": "work", "remaining": 20},
        "todos": [],
    })
    out = tmp_path / "out.png"

    async def inside_loop():
        render.render_to_png(render.build_context(), str(out))

    asyncio.run(inside_loop())   # establishes a running loop; sync render must not error
    assert out.exists()
    with Image.open(out) as im:
        assert im.size == (800, 480)


def test_pomodoro_states():
    tz = ZoneInfo("Asia/Shanghai")
    assert render.pomodoro_state(datetime(2026, 8, 2, 8, 30, tzinfo=tz)) == {"active": False}   # before lookahead window
    assert render.pomodoro_state(datetime(2026, 8, 2, 8, 55, tzinfo=tz)) == {"active": True, "phase": "work", "remaining": 25}   # 8:55 pre-render lookahead -> 9:00 state
    assert render.pomodoro_state(datetime(2026, 8, 2, 8, 59, tzinfo=tz)) == {"active": True, "phase": "work", "remaining": 25}   # still lookahead
    assert render.pomodoro_state(datetime(2026, 8, 2, 21, 0, tzinfo=tz)) == {"active": False}
    assert render.pomodoro_state(datetime(2026, 8, 2, 9, 0, tzinfo=tz)) == {"active": True, "phase": "work", "remaining": 25}
    assert render.pomodoro_state(datetime(2026, 8, 2, 9, 10, tzinfo=tz)) == {"active": True, "phase": "work", "remaining": 15}
    assert render.pomodoro_state(datetime(2026, 8, 2, 9, 25, tzinfo=tz)) == {"active": True, "phase": "break", "remaining": 5}
    assert render.pomodoro_state(datetime(2026, 8, 2, 9, 30, tzinfo=tz)) == {"active": True, "phase": "work", "remaining": 25}
    assert render.pomodoro_state(datetime(2026, 8, 2, 12, 0, tzinfo=tz)) == {"active": True, "phase": "pause", "label": "午休", "end_hm": "13:30"}
    assert render.pomodoro_state(datetime(2026, 8, 2, 13, 0, tzinfo=tz)) == {"active": True, "phase": "pause", "label": "午休", "end_hm": "13:30"}
    assert render.pomodoro_state(datetime(2026, 8, 2, 13, 30, tzinfo=tz))["phase"] != "pause"   # pause ended -> back to cycle
    assert render.pomodoro_state(datetime(2026, 8, 2, 18, 30, tzinfo=tz)) == {"active": True, "phase": "pause", "label": "晚餐", "end_hm": "19:00"}


def test_pomodoro_pause_is_a_true_pause(monkeypatch):
    # 非倍数窗口（45min）：验证午餐和晚餐都是 true pause —— 从时钟扣除，而非穿透。
    # 注意：break_windows 是 Settings() 构造时解析缓存的派生字段，所以直接 patch
    # 结构化列表（patch 原始 breaks 字符串不会触发重新解析）。
    from config import Break
    monkeypatch.setattr(render.settings, "break_windows", [
        Break(720, 765, "午休", "12:45"),    # 12:00–12:45
        Break(1080, 1125, "晚餐", "18:45"),  # 18:00–18:45
    ])
    tz = ZoneInfo("Asia/Shanghai")
    # 12:00 命中午休
    assert render.pomodoro_state(datetime(2026, 8, 2, 12, 0, tzinfo=tz)) == {"active": True, "phase": "pause", "label": "午休", "end_hm": "12:45"}
    # 12:45 午休结束 → work remaining 25（45min 已扣除；若穿透会是 work 10）
    assert render.pomodoro_state(datetime(2026, 8, 2, 12, 45, tzinfo=tz)) == {"active": True, "phase": "work", "remaining": 25}
    # 18:00 命中晚餐
    assert render.pomodoro_state(datetime(2026, 8, 2, 18, 0, tzinfo=tz)) == {"active": True, "phase": "pause", "label": "晚餐", "end_hm": "18:45"}
    # 19:00 晚餐后 → work remaining 25（午+晚共 90min 都已扣除；若不扣晚餐会是 work 10）
    assert render.pomodoro_state(datetime(2026, 8, 2, 19, 0, tzinfo=tz)) == {"active": True, "phase": "work", "remaining": 25}


def test_lunar_str():
    tz = ZoneInfo("Asia/Shanghai")
    assert render._lunar_str(datetime(2026, 8, 2, 9, 41, tzinfo=tz)) == "六月二十"


def test_weather_cache(monkeypatch):
    render._weather_cache.clear()
    calls = []
    monkeypatch.setattr(render.weather, "fetch_weather",
                        lambda *a, **k: calls.append(1) or WeatherData(current={"temp": 28}))
    render._fetch_weather_cached()      # fetch
    render._fetch_weather_cached()      # served from cache
    assert len(calls) == 1
    render._weather_cache["ts"] = 0     # expire the cache
    render._fetch_weather_cached()      # refetch
    assert len(calls) == 2
    render._weather_cache["hour"] = -1  # simulate crossing an hour boundary
    render._fetch_weather_cached()      # refetch despite fresh TTL
    assert len(calls) == 3


def test_build_context_survives_sht40_failure(monkeypatch):
    # SenseCraft down -> build_context must degrade the indoor panel, not kill the render.
    monkeypatch.setattr(render.sht40, "fetch_sht40",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("sensecraft down")))
    monkeypatch.setattr(render.weather, "fetch_weather",
                        lambda *a, **k: WeatherData(current={"temp": 28, "text": "多云", "icon": "104"}, hi=29, lo=21))
    render._weather_cache.clear()
    monkeypatch.setattr(render, "_todos_for_dashboard", lambda: [])
    ctx = render.build_context(now=datetime(2026, 8, 2, 9, 41))
    assert ctx["indoor"].temp is None and ctx["indoor"].humidity is None   # degraded
    assert ctx["weather"].current["temp"] == 28                            # weather still rendered


def test_build_context_survives_weather_failure(monkeypatch):
    # QWeather down with no prior cache -> build_context must degrade weather, not kill the render.
    monkeypatch.setattr(render.weather, "fetch_weather",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("qweather down")))
    monkeypatch.setattr(render.sht40, "fetch_sht40",
                        lambda *a, **k: Sht40Data(temp=26.0, humidity=42.0, battery=87))
    render._weather_cache.clear()
    monkeypatch.setattr(render, "_todos_for_dashboard", lambda: [])
    ctx = render.build_context(now=datetime(2026, 8, 2, 9, 41))
    assert ctx["indoor"].temp == 26.0                                      # indoor still rendered
    assert ctx["weather"].current == {}                                    # weather degraded to empty


def test_fetch_weather_cached_falls_back_to_stale_cache(monkeypatch):
    # A fresh re-fetch that raises must return the previously cached data, not propagate.
    render._weather_cache.clear()
    good = WeatherData(current={"temp": 28, "text": "多云"})
    calls = []

    def fetch_then_fail(*a, **k):
        calls.append(1)
        return good if len(calls) == 1 else (_ for _ in ()).throw(RuntimeError("qweather down"))

    monkeypatch.setattr(render.weather, "fetch_weather", fetch_then_fail)
    first = render._fetch_weather_cached()          # succeeds, populates cache
    assert first.current["temp"] == 28
    render._weather_cache["ts"] = 0.0                # force a cache miss on next call
    render._weather_cache["hour"] = -1
    second = render._fetch_weather_cached()          # fetch raises -> must fall back to stale cache
    assert second.current["temp"] == 28              # stale data served, no exception
    assert len(calls) == 2


def test_render_now_serializes_concurrent_calls(monkeypatch):
    # Overlapping scheduler jobs must not run Playwright / mutate the shared cache concurrently.
    state = threading.Lock()
    cur = {"n": 0}
    peak = {"n": 0}

    def slow(_ctx):
        with state:
            cur["n"] += 1
            peak["n"] = max(peak["n"], cur["n"])
        time.sleep(0.1)
        with state:
            cur["n"] -= 1

    monkeypatch.setattr(render, "build_context", lambda: {})
    monkeypatch.setattr(render, "render_to_png", slow)
    threads = [threading.Thread(target=render.render_now) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak["n"] == 1                            # renders serialized


def test_render_to_png_propagates_error_from_worker_thread(tmp_path, monkeypatch):
    # The in_loop path runs _screenshot on a worker thread; its errors must surface, not vanish.
    monkeypatch.setattr(render, "render_html", lambda ctx: "<html></html>")
    monkeypatch.setattr(render, "_screenshot", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("chromium died")))
    out = tmp_path / "out.png"

    async def inside_loop():
        render.render_to_png({}, str(out))

    with pytest.raises(RuntimeError, match="chromium died"):
        asyncio.run(inside_loop())


def _pomodoro_ctx(pomodoro):
    return {
        "time_str": "09:41", "date_str": "2026.08.02", "weekday": "星期日",
        "indoor": render.sht40.Sht40Data(temp=26.0, humidity=42.0, battery=87),
        "weather": render.weather.WeatherData(
            current={"temp": 28, "text": "多云", "icon": "104"}, hi=29, lo=21, aqi=45,
            hourly=[{"label": "现在", "text": "多云", "temp": 28, "rain": 34}],
            sunrise="05:42", sunset="19:08"),
        "lunar": "六月二十", "pomodoro": pomodoro, "todos": [],
    }


def test_template_pause_branch_uses_label_and_end_hm():
    # pause 分支由 label 数据驱动：晚餐显示「晚餐 · 19:00」，不再硬编码「午休」
    html = render.render_html(_pomodoro_ctx(
        {"active": True, "phase": "pause", "label": "晚餐", "end_hm": "19:00"}))
    assert "晚餐" in html and "19:00" in html
    assert "午休" not in html


def test_template_break_copy_is_fangsong():
    # break 短休息文案改为「放松」，不再出现「走动 / 喝水」
    html = render.render_html(_pomodoro_ctx(
        {"active": True, "phase": "break", "remaining": 5}))
    assert "放松" in html
    assert "走动" not in html
    assert "喝水" not in html


def test_prio_marker_mapping():
    assert render.prio_marker("high") == "●"
    assert render.prio_marker("normal") == "●"
    assert render.prio_marker("low") == "○"
    assert render.prio_marker("urgent") == "●"   # unknown -> fallback to solid black


def test_template_shows_prio_markers():
    from todos.db import Todo
    ctx = {
        "time_str": "09:41", "date_str": "2026.08.02", "weekday": "星期日",
        "indoor": render.sht40.Sht40Data(temp=26.0, humidity=42.0, battery=87),
        "weather": render.weather.WeatherData(
            current={"temp": 28, "text": "多云", "icon": "104"}, hi=29, lo=21, aqi=45,
            hourly=[{"label": "现在", "text": "多云", "temp": 28, "rain": 34}],
            sunrise="05:42", sunset="19:00"),
        "lunar": "六月二十",
        "pomodoro": {"active": True, "phase": "work", "remaining": 20},
        "todos": [
            Todo(1, "紧要事项", False, "high", "2026-08-03T00:00:00+00:00"),
            Todo(2, "普通事项", False, "normal", "2026-08-03T00:00:00+00:00"),
            Todo(3, "从容事项", False, "low", "2026-08-03T00:00:00+00:00"),
        ],
    }
    html = render.render_html(ctx)
    assert '<span class="pmark high">●</span>' in html
    assert '<span class="pmark normal">●</span>' in html
    assert '<span class="pmark low">○</span>' in html
