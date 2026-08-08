from datetime import datetime
from zoneinfo import ZoneInfo
import render
from fetchers.sht40 import Sht40Data
from fetchers.weather import WeatherData
from fetchers.gold import GoldData


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
    # 2026-08-02 is a Sunday — now a rest day, so no pomodoro state
    assert ctx["pomodoro"] == {"active": False}
    assert ctx["lunar"] == "六月二十"
    assert ctx["todos"][0].title == "回复邮件"


def test_build_context_includes_day_name_and_type(monkeypatch):
    from daytypes import Calendar
    monkeypatch.setattr(render, "calendar",
                        Calendar({"overrides": {"2026-10-01": {"type": "rest", "name": "国庆节"}}}))
    monkeypatch.setattr(render.sht40, "fetch_sht40",
                        lambda *a, **k: Sht40Data(temp=26.0, humidity=42.0, battery=87))
    monkeypatch.setattr(render.weather, "fetch_weather",
                        lambda *a, **k: WeatherData(current={"temp": 28}))
    monkeypatch.setattr(render, "_todos_for_dashboard", lambda: [])
    render._weather_cache.clear()
    ctx = render.build_context(now=datetime(2026, 10, 1, 9, 0))
    assert ctx["day_type"] == "rest" and ctx["day_name"] == "国庆节"
    ctx2 = render.build_context(now=datetime(2026, 8, 3, 9, 0))   # Monday
    assert ctx2["day_type"] == "workday" and ctx2["day_name"] == ""


def test_template_date_row_shows_day_name():
    ctx = _pomodoro_ctx({"active": True, "phase": "work", "remaining": 20})
    ctx["day_name"] = "国庆节"
    assert "· 国庆节" in render.render_html(ctx)
    ctx2 = _pomodoro_ctx({"active": True, "phase": "work", "remaining": 20})
    ctx2["day_name"] = ""
    assert "· 国庆节" not in render.render_html(ctx2)


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
    # 2026-08-03 is a Monday (workday window 9-21)
    assert render.pomodoro_state(datetime(2026, 8, 3, 8, 30, tzinfo=tz)) == {"active": False}   # before lookahead window
    assert render.pomodoro_state(datetime(2026, 8, 3, 8, 55, tzinfo=tz)) == {"active": True, "phase": "work", "remaining": 25}   # 8:55 pre-render lookahead -> 9:00 state
    assert render.pomodoro_state(datetime(2026, 8, 3, 8, 59, tzinfo=tz)) == {"active": True, "phase": "work", "remaining": 25}   # still lookahead
    assert render.pomodoro_state(datetime(2026, 8, 3, 21, 0, tzinfo=tz)) == {"active": False}
    assert render.pomodoro_state(datetime(2026, 8, 3, 9, 0, tzinfo=tz)) == {"active": True, "phase": "work", "remaining": 25}
    assert render.pomodoro_state(datetime(2026, 8, 3, 9, 10, tzinfo=tz)) == {"active": True, "phase": "work", "remaining": 15}
    assert render.pomodoro_state(datetime(2026, 8, 3, 9, 25, tzinfo=tz)) == {"active": True, "phase": "break", "remaining": 5}
    assert render.pomodoro_state(datetime(2026, 8, 3, 9, 30, tzinfo=tz)) == {"active": True, "phase": "work", "remaining": 25}
    assert render.pomodoro_state(datetime(2026, 8, 3, 12, 0, tzinfo=tz)) == {"active": True, "phase": "pause", "label": "午休", "end_hm": "13:30"}
    assert render.pomodoro_state(datetime(2026, 8, 3, 13, 30, tzinfo=tz))["phase"] != "pause"   # pause ended -> back to cycle
    assert render.pomodoro_state(datetime(2026, 8, 3, 18, 30, tzinfo=tz)) == {"active": True, "phase": "pause", "label": "晚餐", "end_hm": "19:00"}


def test_pomodoro_inactive_on_rest_days():
    """Weekends and holidays are rest days — no pomodoro state at all."""
    tz = ZoneInfo("Asia/Shanghai")
    assert render.pomodoro_state(datetime(2026, 8, 2, 9, 0, tzinfo=tz)) == {"active": False}   # Sunday
    assert render.pomodoro_state(datetime(2026, 8, 8, 9, 0, tzinfo=tz)) == {"active": False}   # Saturday
    assert render.pomodoro_state(datetime(2026, 8, 2, 12, 0, tzinfo=tz)) == {"active": False}  # lunch time on rest day


def test_pomodoro_friday_ends_early():
    """Friday uses the friday day-type window (9-18) — closes at 18:00 instead of 21:00."""
    tz = ZoneInfo("Asia/Shanghai")
    # 2026-08-07 is a Friday
    # 17:55 — still active (inside Friday window)
    assert render.pomodoro_state(datetime(2026, 8, 7, 17, 55, tzinfo=tz))["active"] is True
    # 18:00 — inactive (end is exclusive, Friday window closed)
    assert render.pomodoro_state(datetime(2026, 8, 7, 18, 0, tzinfo=tz)) == {"active": False}
    # 20:00 — would be active on Mon-Thu, but inactive on Friday
    assert render.pomodoro_state(datetime(2026, 8, 7, 20, 0, tzinfo=tz)) == {"active": False}
    # 21:00 — same, inactive on Friday
    assert render.pomodoro_state(datetime(2026, 8, 7, 21, 0, tzinfo=tz)) == {"active": False}


def test_pomodoro_pause_is_a_true_pause(monkeypatch):
    # 非倍数窗口（45min）：验证午餐和晚餐都是 true pause —— 从时钟扣除，而非穿透。
    from daytypes import Break
    monkeypatch.setattr(render.calendar, "breaks", [
        Break(720, 765, "午休", "12:45"),    # 12:00–12:45
        Break(1080, 1125, "晚餐", "18:45"),  # 18:00–18:45
    ])
    tz = ZoneInfo("Asia/Shanghai")
    assert render.pomodoro_state(datetime(2026, 8, 3, 12, 0, tzinfo=tz)) == {"active": True, "phase": "pause", "label": "午休", "end_hm": "12:45"}
    assert render.pomodoro_state(datetime(2026, 8, 3, 12, 45, tzinfo=tz)) == {"active": True, "phase": "work", "remaining": 25}
    assert render.pomodoro_state(datetime(2026, 8, 3, 18, 0, tzinfo=tz)) == {"active": True, "phase": "pause", "label": "晚餐", "end_hm": "18:45"}
    assert render.pomodoro_state(datetime(2026, 8, 3, 19, 0, tzinfo=tz)) == {"active": True, "phase": "work", "remaining": 25}


def test_lunar_str():
    tz = ZoneInfo("Asia/Shanghai")
    assert render._lunar_str(datetime(2026, 8, 2, 9, 41, tzinfo=tz)) == "六月二十"


def test_template_focus_card_header_is_neutral():
    # 标题固定为中性词「状态」——休息日/工作日通用，不随类型变化
    html = render.render_html(_pomodoro_ctx({"active": True, "phase": "work", "remaining": 20}))
    assert '<div class="hd">状态</div>' in html
    assert '<div class="hd">专注</div>' not in html


def test_template_focus_card_shows_rest_day():
    # 休息日渲染完整主画面，专注卡片显示休息状态（含节日名）
    ctx = _pomodoro_ctx({"active": False})
    ctx["day_type"] = "rest"
    ctx["day_name"] = "国庆节"
    html = render.render_html(ctx)
    assert "休息日 · 国庆节" in html
    assert "今日已结束" not in html
    # 工作日不显示休息日
    ctx2 = _pomodoro_ctx({"active": False})
    ctx2["day_type"] = "workday"
    ctx2["day_name"] = ""
    assert "休息日" not in render.render_html(ctx2)


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


def test_build_context_includes_gold(monkeypatch):
    """build_context must include a 'gold' key with GoldData from the cache."""
    # stub weather + indoor + todos
    monkeypatch.setattr(render.sht40, "fetch_sht40",
                        lambda *a, **k: Sht40Data(temp=26.0, humidity=42.0, battery=87))
    monkeypatch.setattr(render.weather, "fetch_weather",
                        lambda *a, **k: WeatherData(current={"temp": 28}))
    render._weather_cache.clear()
    render._gold_cache.clear()
    monkeypatch.setattr(render, "_todos_for_dashboard", lambda: [])

    # stub gold fetch
    mock_gold = GoldData(current=760.5, open=755.0, high=762.8, low=753.2,
                         points=[{"time": "09:00:00", "price": 755.0},
                                 {"time": "10:00:00", "price": 760.5}])
    monkeypatch.setattr(render.gold_fetcher, "fetch_gold_intraday",
                        lambda symbol: mock_gold)

    ctx = render.build_context(now=datetime(2026, 8, 3, 10, 0))
    assert ctx["gold"] is not None
    assert ctx["gold"].current == 760.5
    assert ctx["gold"].open == 755.0
    assert len(ctx["gold"].points) == 2


def test_gold_cache_reuses_within_window(monkeypatch):
    """Gold cache reuses data within weather_cache_min and same hour."""
    render._gold_cache.clear()
    calls = []
    mock_gold = GoldData(current=760.5)
    monkeypatch.setattr(render.gold_fetcher, "fetch_gold_intraday",
                        lambda symbol: (calls.append(1), mock_gold)[1])

    render._fetch_gold_cached()        # fetch
    render._fetch_gold_cached()        # served from cache
    assert len(calls) == 1
    render._gold_cache["ts"] = 0.0     # expire TTL
    render._gold_cache["hour"] = -1    # cross hour boundary
    render._fetch_gold_cached()        # refetch
    assert len(calls) == 2


def test_gold_cache_falls_back_to_stale(monkeypatch):
    """A failed re-fetch returns stale cache, not None."""
    render._gold_cache.clear()
    good = GoldData(current=760.5)
    calls = []

    def fetch_then_fail(symbol):
        calls.append(1)
        if len(calls) == 1:
            return good
        raise RuntimeError("akshare down")

    monkeypatch.setattr(render.gold_fetcher, "fetch_gold_intraday", fetch_then_fail)
    first = render._fetch_gold_cached()          # succeeds
    assert first.current == 760.5
    render._gold_cache["ts"] = 0.0               # force cache miss
    render._gold_cache["hour"] = -1
    second = render._fetch_gold_cached()          # fetch raises -> fall back
    assert second.current == 760.5                # stale data served
    assert len(calls) == 2


def test_template_gold_card_renders_chart():
    """Template must render the gold card with chart SVG when data is present."""
    ctx = _pomodoro_ctx({"active": True, "phase": "work", "remaining": 20})
    ctx["gold"] = GoldData(
        current=760.50, open=755.00, high=762.80, low=753.20,
        points=[{"time": "09:00:00", "price": 755.0},
                {"time": "10:00:00", "price": 760.5}],
    )
    html = render.render_html(ctx)
    # Card header
    assert "Au99.99" in html
    assert "760.50" in html
    # SVG chart
    assert "<polyline" in html
    assert 'stroke="#0a0a0a"' in html
    # Summary row
    assert "755.00" in html
    assert "762.80" in html
    assert "753.20" in html


def test_template_gold_card_shows_placeholder_when_no_data():
    """Gold card shows '--' when gold is None (fetch failed, no cache)."""
    ctx = _pomodoro_ctx({"active": True, "phase": "work", "remaining": 20})
    ctx["gold"] = None
    html = render.render_html(ctx)
    assert "Au99.99" in html          # card header still renders
    assert "--" in html               # placeholder
    assert "<polyline" not in html    # no chart


def test_gold_chart_svg_empty_points():
    """gold_chart_svg returns placeholder when points list is empty."""
    svg = render.gold_chart_svg([])
    assert "--" in svg
    assert "<polyline" not in svg


def test_gold_chart_svg_zero_range():
    """gold_chart_svg handles flat price (lo == hi) without division by zero."""
    svg = render.gold_chart_svg([
        {"time": "09:00:00", "price": 755.0},
        {"time": "10:00:00", "price": 755.0},
    ])
    assert "<polyline" in svg       # still renders the line (flat)


