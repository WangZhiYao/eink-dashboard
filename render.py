import asyncio
import logging
import os
import threading
import time
import lunardate
from datetime import datetime
from zoneinfo import ZoneInfo

from config import settings
from daytypes import calendar  # 模块级单例（Calendar.load(settings.calendar_file)）
from fetchers import sht40, weather
from fetchers import gold as gold_fetcher
from todos import db as todos_db
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright

WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
OUT_PATH = "static/dashboard.png"

_LUNAR_MONTHS = ["正月", "二月", "三月", "四月", "五月", "六月", "七月", "八月", "九月", "十月", "冬月", "腊月"]
_LUNAR_DAY_DIGITS = "一二三四五六七八九"


def _lunar_str(d: datetime) -> str:
    """Solar -> Chinese lunar date string, e.g. '七月初一'."""
    ld = lunardate.LunarDate.from_solar_date(d.year, d.month, d.day)
    month = ("闰" if ld.is_leap_month else "") + _LUNAR_MONTHS[ld.month - 1]
    day = ld.day
    if day == 10:
        dayname = "初十"
    elif day == 20:
        dayname = "二十"
    elif day == 30:
        dayname = "三十"
    elif day < 10:
        dayname = "初" + _LUNAR_DAY_DIGITS[day - 1]
    elif day < 20:
        dayname = "十" + _LUNAR_DAY_DIGITS[day - 11]
    else:
        dayname = "廿" + _LUNAR_DAY_DIGITS[day - 21]
    return month + dayname


WORK_MIN = 25
BREAK_MIN = 5
CYCLE_MIN = WORK_MIN + BREAK_MIN  # 30


def pomodoro_state(now: datetime) -> dict:
    """Clock-anchored 25/5 Pomodoro, active during the day-type's window,
    with calendar breaks as *true pauses* (folded out of the clock).
    Rest days (weekends / holidays) return inactive — no pomodoro there.

    Pre-render lookahead: during the final render_interval_min before `start`
    (e.g. 8:55-8:59), show the upcoming start state so the image is ready when
    SenseCraft pulls at 9:00. Lookahead only fires in the pre-start window
    (morning), so it can never land inside a midday/evening pause.
    """
    dt = calendar.day_type(now.date())
    if dt.simple or dt.start is None or dt.end is None:
        return {"active": False}
    now_min = now.hour * 60 + now.minute
    if dt.start - calendar.render_interval_min <= now_min < dt.start:
        eff_min = dt.start            # 8:55-8:59 -> show the 9:00 start state
    else:
        eff_min = now_min
    if eff_min < dt.start or eff_min >= dt.end:
        return {"active": False}
    for b in calendar.breaks:
        if b.start <= now_min < b.end:
            return {"active": True, "phase": "pause", "label": b.label, "end_hm": b.end_hm}
    # Fold every pause window that has fully passed out of the clock, so the
    # cycle resumes where it left off after each pause (a true pause).
    folded = eff_min
    for b in calendar.breaks:
        if eff_min >= b.end:
            folded -= (b.end - b.start)
    pos = (folded - dt.start) % CYCLE_MIN
    if pos < WORK_MIN:
        return {"active": True, "phase": "work", "remaining": WORK_MIN - pos}
    return {"active": True, "phase": "break", "remaining": CYCLE_MIN - pos}


_weather_cache = {"data": None, "ts": 0.0}

_gold_cache = {"data": None, "ts": 0.0, "session": None}


def _gold_session_key(now: datetime) -> str:
    """Return a cache key that changes at gold trading session boundaries.

    The trading-day view computed by fetch_gold_intraday() changes at:
      02:30 — reference date shifts from yesterday to today
      09:00 — day session opens (fresh data)
      20:00 — night session opens, reference shifts to tomorrow
    """
    hm = now.hour * 60 + now.minute
    if hm < 150:                    # 00:00 – 02:30
        segment = "night-end"
    elif hm < 540:                  # 02:30 – 09:00
        segment = "pre-open"
    elif hm < 1200:                 # 09:00 – 20:00
        segment = "day"
    else:                           # 20:00 – 23:59
        segment = "night-start"
    return f"{now.strftime('%Y-%m-%d')}-{segment}"


def _fetch_weather_cached() -> weather.WeatherData:
    """Serve cached QWeather data while within weather_cache_min AND the same hour;
    otherwise re-fetch. The same-hour check refreshes at each hour boundary so the
    hourly forecast / current-hour framing stays correct."""
    now = time.monotonic()
    cur_hour = datetime.now(ZoneInfo(settings.tz)).hour
    cached = _weather_cache.get("data")
    if (cached is not None
            and now - _weather_cache.get("ts", 0.0) < calendar.weather_cache_min * 60
            and _weather_cache.get("hour") == cur_hour):
        return cached
    try:
        data = weather.fetch_weather(settings.qweather_host, settings.qweather_api_key, settings.qweather_location)
    except Exception:
        # Transient outage: serve stale cache if we have it, else a degraded
        # (empty) payload so the rest of the dashboard still renders.
        log.warning("weather fetch failed; serving %s", "stale cache" if cached is not None else "degraded", exc_info=True)
        return cached if cached is not None else weather.WeatherData(current={})
    _weather_cache["data"] = data
    _weather_cache["ts"] = now
    _weather_cache["hour"] = cur_hour
    return data


def _fetch_gold_cached() -> gold_fetcher.GoldData | None:
    """Serve cached gold data while within weather_cache_min AND the same
    trading session; otherwise re-fetch. Returns None when no data is
    available (never cached and fetch failed)."""
    now = time.monotonic()
    cur_session = _gold_session_key(datetime.now(ZoneInfo(settings.tz)))
    cached = _gold_cache.get("data")
    if (cached is not None
            and now - _gold_cache.get("ts", 0.0) < calendar.weather_cache_min * 60
            and _gold_cache.get("session") == cur_session):
        return cached
    try:
        data = gold_fetcher.fetch_gold_intraday("Au99.99")
    except Exception:
        log.warning("gold fetch failed; serving %s", "stale cache" if cached is not None else "degraded", exc_info=True)
        return cached if cached is not None else None
    # Don't cache empty data (prevents a transient empty response from poisoning
    # the cache for the rest of the session).
    if data.current is None and cached is not None:
        log.warning("gold fetch returned empty; keeping stale cache")
        return cached
    _gold_cache["data"] = data
    _gold_cache["ts"] = now
    _gold_cache["session"] = cur_session
    return data


def _todos_for_dashboard() -> list:
    """Not-done todos for the dashboard (<=6, prio-sorted). Empty on any error."""
    try:
        return todos_db.list_todos(settings.todo_db, include_done=False)[:6]
    except Exception:
        log.warning("todo fetch failed; serving empty list", exc_info=True)
        return []


def build_context(now: datetime | None = None) -> dict:
    now = now or datetime.now(ZoneInfo(settings.tz))
    dt = calendar.day_type(now.date())
    try:
        indoor = sht40.fetch_sht40(settings.sensecraft_device_id, settings.sensecraft_api_key)
    except Exception:
        # SenseCraft outage: degrade the indoor panel rather than blanking the whole screen.
        log.warning("indoor (SHT40) fetch failed; serving degraded", exc_info=True)
        indoor = sht40.Sht40Data(temp=None, humidity=None, battery=None)
    wx = _fetch_weather_cached()
    g = _fetch_gold_cached()
    return {
        "time_str": now.strftime("%H:%M"),
        "date_str": now.strftime("%Y.%m.%d"),
        "weekday": WEEKDAYS[now.weekday()],
        "indoor": indoor,
        "weather": wx,
        "lunar": _lunar_str(now),
        "pomodoro": pomodoro_state(now),
        "todos": _todos_for_dashboard(),
        "day_name": dt.name or "",
        "day_type": dt.type_name,
        "gold": g,
    }


_env = Environment(loader=FileSystemLoader("templates"), autoescape=select_autoescape(["html"]))
log = logging.getLogger("render")


# Inline monochrome SVGs for common QWeather icon codes (font-independent).
_SVG = {
    "sun": '<circle cx="16" cy="16" r="6"/><g stroke="#0a0a0a" stroke-width="2" stroke-linecap="round">'
           '<line x1="16" y1="3" x2="16" y2="7"/><line x1="16" y1="25" x2="16" y2="29"/>'
           '<line x1="3" y1="16" x2="7" y2="16"/><line x1="25" y1="16" x2="29" y2="16"/>'
           '<line x1="7" y1="7" x2="9.5" y2="9.5"/><line x1="22.5" y1="22.5" x2="25" y2="25"/>'
           '<line x1="25" y1="7" x2="22.5" y2="9.5"/><line x1="9.5" y1="22.5" x2="7" y2="25"/></g>',
    "cloud": '<path d="M9 20a5 5 0 0 1 .6-9.98A6 6 0 0 1 21 12.5a4 4 0 0 1-.5 7.5z"/>',
    "rain": '<path d="M9 18a5 5 0 0 1 .6-9.98A6 6 0 0 1 21 10.5a4 4 0 0 1-.5 7.5z"/>'
             '<g stroke="#0a0a0a" stroke-width="2" stroke-linecap="round">'
             '<line x1="11" y1="23" x2="10" y2="27"/><line x1="17" y1="23" x2="16" y2="27"/>'
             '<line x1="23" y1="23" x2="22" y2="27"/></g>',
}


def _icon_kind(code: str) -> str:
    c = (code or "").lstrip()
    if not c:
        return "cloud"
    n = int(c) if c.isdigit() else 0
    if n in (100,) or 150 <= n < 200:
        return "sun"
    if 300 <= n < 500:
        return "rain"
    return "cloud"


_PRIO_MARKERS = {"high": "●", "normal": "●", "low": "○"}


def prio_marker(prio: str) -> str:
    """Priority marker glyph for the e-ink dashboard. Shape only distinguishes
    solid vs hollow; color comes from the CSS class (.pmark.normal = gray)."""
    return _PRIO_MARKERS.get(prio, "●")


def gold_chart_svg(points: list, width: int = 166, height: int = 64) -> str:
    """Build an inline monochrome SVG line chart from gold data points.
    Returns an <svg> element with a polyline — no JS, no external deps.

    X axis is proportional to TRADING time, not point index: the night session
    (20:00→02:30) maps to the left half and the day session (09:00→15:30) to
    the right half — an Alipay-style 分时图. With index spacing the ~390 night
    points would crush the day session to a sliver whenever the render happens
    mid-morning.
    """
    if not points:
        return '<svg class="ic" viewBox="0 0 %d %d"><text x="%d" y="%d" text-anchor="middle" font-size="12" fill="#5f5f5f">--</text></svg>' % (width, height, width // 2, height // 2 + 4)

    def _tmin(t: str) -> int:
        return int(t[:2]) * 60 + int(t[3:5])

    # Session timeline in trading minutes: night 20:00(-240 offset from midnight
    # → 0) …02:30 = 390 min, then day 09:00(=390)…15:30 = 780 min.
    def _trading_min(t: str) -> int:
        m = _tmin(t)
        if m >= 20 * 60:          # evening slice: 20:00→24:00 = 0→240
            return m - 20 * 60
        return m + 4 * 60         # morning/day slice: 0→4:30=240…, 09:00=390, 15:30=780

    SPAN = 780                    # total trading minutes
    prices = [p["price"] for p in points]
    lo, hi = min(prices), max(prices)
    if hi == lo:
        hi = lo + 1.0  # avoid zero-range

    # Y scale with 10% padding
    pad = (hi - lo) * 0.1
    y_min, y_max = lo - pad, hi + pad

    # Padding: horizontal prevents label/dot clipping; vertical reserves space
    # below the chart for time labels so the polyline doesn't overlap them.
    pad_x = 10
    pad_y_bottom = 12
    pad_y_top = 6
    chart_w = width - 2 * pad_x
    chart_h = height - pad_y_top - pad_y_bottom

    def _x(t: str) -> float:
        return pad_x + (_trading_min(t) / SPAN) * chart_w

    def _y(price: float) -> float:
        return pad_y_top + chart_h - ((price - y_min) / (y_max - y_min)) * chart_h

    # Build polyline points string
    pts = " ".join(f"{_x(p['time']):.1f},{_y(p['price']):.1f}" for p in points)

    # X-axis: FIXED full trading span (0→780). Labels always render — the
    # chart is an Alipay-style 分时图 where the line grows rightward over
    # the trading day, so ticks exist whether or not data covers them yet.
    mid_x = pad_x + chart_w / 2

    # Session divider at the 02:30/09:00 boundary (trading minute 390).
    divider = (
        f'<line x1="{mid_x:.1f}" y1="{pad_y_top}" x2="{mid_x:.1f}" '
        f'y2="{height - pad_y_bottom}" stroke="#c0c0c0" '
        f'stroke-dasharray="2,2" stroke-width="1"/>'
    )

    # (x, label, text-anchor): ends flush to the chart edge, the 02:30/09:00
    # pair splits around the divider — 02:30 right-aligned left of it,
    # 09:00 left-aligned right of it.
    labels = [
        (pad_x, "20:00", "start"),
        (mid_x - 2, "02:30", "end"),
        (mid_x + 2, "09:00", "start"),
        (width - pad_x, "15:30", "end"),
    ]
    label_html = "".join(
        f'<text x="{x:.1f}" y="{height - 2}" text-anchor="{anchor}" '
        f'font-size="7" fill="#5f5f5f">{label}</text>'
        for x, label, anchor in labels
    )
    # Current price dot at the end
    last_x, last_y = _x(points[-1]["time"]), _y(prices[-1])

    return (
        f'<svg class="ic" viewBox="0 0 {width} {height}" style="width:100%;height:auto;">'
        f'{divider}'
        f'<polyline points="{pts}" fill="none" stroke="#0a0a0a" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/>'
        f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="2.5" fill="#0a0a0a"/>'
        f'{label_html}'
        f'</svg>'
    )


_env.globals["gold_chart_svg"] = gold_chart_svg


def wx_icon_svg(code: str) -> str:
    body = _SVG.get(_icon_kind(code), _SVG["cloud"])
    return f'<svg class="ic" viewBox="0 0 32 32">{body}</svg>'


_env.globals["wx_icon_svg"] = wx_icon_svg
_env.globals["prio_marker"] = prio_marker


def render_html(context: dict) -> str:
    return _env.get_template("dashboard.html").render(**context)


def _screenshot(html_str: str, out_path: str) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 800, "height": 480})
        page.set_content(html_str, wait_until="load")
        page.screenshot(path=out_path, clip={"x": 0, "y": 0, "width": 800, "height": 480})
        browser.close()


def _html_to_png(html_str: str, out_path: str) -> None:
    root, ext = os.path.splitext(out_path)
    tmp = f"{root}.tmp{ext}"          # keep .png suffix — Playwright infers format from extension
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)   # Fix #5: ensure dir exists
    # Playwright's sync API refuses to run inside a running asyncio loop
    # (e.g. FastAPI's lifespan). When one is running, dispatch the sync
    # screenshot to a worker thread — no loop is running there. We never use
    # asyncio.run here, so this is safe to call from the lifespan.
    try:
        asyncio.get_running_loop()
        in_loop = True
    except RuntimeError:
        in_loop = False
    if in_loop:
        # sync Playwright can't run inside a running asyncio loop; run it on a
        # worker thread, but surface any error back to the caller instead of
        # letting the thread boundary swallow it.
        holder: dict = {}

        def _run():
            try:
                _screenshot(html_str, tmp)
            except BaseException as e:  # re-raised in the caller thread
                holder["error"] = e

        t = threading.Thread(target=_run)
        t.start()
        t.join()
        if "error" in holder:
            raise holder["error"]
    else:
        _screenshot(html_str, tmp)
    os.replace(tmp, out_path)


def render_to_png(context: dict, out_path: str = OUT_PATH) -> None:
    _html_to_png(render_html(context), out_path)


_render_lock = threading.Lock()


def render_now() -> None:
    # Serialize renders: APScheduler fires jobs from a thread pool and they can
    # overlap, but Playwright, the shared _weather_cache, and the fixed tmp path
    # are not safe under concurrency.
    with _render_lock:
        try:
            render_to_png(build_context())
            log.info("rendered %s", OUT_PATH)
        except Exception:
            log.exception("render failed")


def render_tick(now: datetime | None = None) -> None:
    """Scheduler entry: decide per day-type whether/how to render.

    workday/friday/small: full render inside [start, end) (plus the pre-render
    lookahead window); rest: full render on every tick from render_at on — the
    layout is the same as a workday, only the focus card shows the rest state,
    so the clock/weather/todos stay live. A failed render is retried by the
    next tick.
    """
    now = now or datetime.now(ZoneInfo(settings.tz))
    now_min = now.hour * 60 + now.minute
    dt = calendar.day_type(now.date())
    if dt.simple:
        if dt.render_at is None or now_min < dt.render_at:
            return
        render_now()
        return
    if dt.start - calendar.render_interval_min <= now_min < dt.start \
            or dt.start <= now_min < dt.end:
        render_now()
