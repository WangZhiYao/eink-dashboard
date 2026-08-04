import asyncio
import logging
import os
import threading
import time
import lunardate
from datetime import datetime
from zoneinfo import ZoneInfo

from config import settings
from fetchers import sht40, weather
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


def _hm_to_min(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def pomodoro_state(now: datetime) -> dict:
    """Clock-anchored 25/5 Pomodoro, active during [pomodoro_start, pomodoro_end) hours,
    with a lunch pause [lunch_start, lunch_end).

    Pre-render lookahead: during the final render_interval_min before `start`
    (e.g. 8:55-8:59), show the upcoming start state so the image is ready when
    SenseCraft pulls at 9:00. With renders aligned to 5-min boundaries, work
    shows remaining 25/20/15/10/5 and the break only ever shows '剩 5 分'.
    """
    start, end = settings.pomodoro_start, settings.pomodoro_end
    now_min = now.hour * 60 + now.minute
    start_min = start * 60
    if start_min - settings.render_interval_min <= now_min < start_min:
        eff_min = start_min            # 8:55-8:59 -> show the 9:00 start state
    else:
        eff_min = now_min
    if eff_min // 60 < start or eff_min // 60 >= end:
        return {"active": False}
    lunch_start, lunch_end = _hm_to_min(settings.lunch_start), _hm_to_min(settings.lunch_end)
    if lunch_start <= now_min < lunch_end:
        return {"active": True, "phase": "lunch", "end_hm": settings.lunch_end}
    # Fold the lunch window out of the clock so the cycle resumes where it left
    # off after lunch (a true pause), instead of advancing through it. No-op when
    # the lunch duration happens to be a multiple of CYCLE_MIN.
    adj = eff_min - (lunch_end - lunch_start) if eff_min >= lunch_end else eff_min
    pos = (adj - start_min) % CYCLE_MIN
    if pos < WORK_MIN:
        return {"active": True, "phase": "work", "remaining": WORK_MIN - pos}
    return {"active": True, "phase": "break", "remaining": CYCLE_MIN - pos}


_weather_cache = {"data": None, "ts": 0.0}


def _fetch_weather_cached() -> weather.WeatherData:
    """Serve cached QWeather data while within weather_cache_min AND the same hour;
    otherwise re-fetch. The same-hour check refreshes at each hour boundary so the
    hourly forecast / current-hour framing stays correct."""
    now = time.monotonic()
    cur_hour = datetime.now(ZoneInfo(settings.tz)).hour
    cached = _weather_cache.get("data")
    if (cached is not None
            and now - _weather_cache.get("ts", 0.0) < settings.weather_cache_min * 60
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


def _todos_for_dashboard() -> list:
    """Not-done todos for the dashboard (<=6, prio-sorted). Empty on any error."""
    try:
        return todos_db.list_todos(settings.todo_db, include_done=False)[:6]
    except Exception:
        log.warning("todo fetch failed; serving empty list", exc_info=True)
        return []


def build_context(now: datetime | None = None) -> dict:
    now = now or datetime.now(ZoneInfo(settings.tz))
    try:
        indoor = sht40.fetch_sht40(settings.sensecraft_device_id, settings.sensecraft_api_key)
    except Exception:
        # SenseCraft outage: degrade the indoor panel rather than blanking the whole screen.
        log.warning("indoor (SHT40) fetch failed; serving degraded", exc_info=True)
        indoor = sht40.Sht40Data(temp=None, humidity=None, battery=None)
    wx = _fetch_weather_cached()
    return {
        "time_str": now.strftime("%H:%M"),
        "date_str": now.strftime("%Y.%m.%d"),
        "weekday": WEEKDAYS[now.weekday()],
        "indoor": indoor,
        "weather": wx,
        "lunar": _lunar_str(now),
        "pomodoro": pomodoro_state(now),
        "todos": _todos_for_dashboard(),
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


def wx_icon_svg(code: str) -> str:
    body = _SVG.get(_icon_kind(code), _SVG["cloud"])
    return f'<svg class="ic" viewBox="0 0 32 32">{body}</svg>'


_env.globals["wx_icon_svg"] = wx_icon_svg


def render_html(context: dict) -> str:
    return _env.get_template("dashboard.html").render(**context)


def _screenshot(html_str: str, out_path: str) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 800, "height": 480})
        page.set_content(html_str, wait_until="load")
        page.screenshot(path=out_path, clip={"x": 0, "y": 0, "width": 800, "height": 480})
        browser.close()


def render_to_png(context: dict, out_path: str = OUT_PATH) -> None:
    html_str = render_html(context)
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
