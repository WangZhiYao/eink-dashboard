"""渲染上下文聚合：取齐各路数据并按来源逐路降级（单路失败不拖垮整屏）。"""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from config import settings
from daytypes import calendar
from fetchers import sht40, weather
from todos import db as todos_db

from render.caches import _fetch_gold_cached, _fetch_weather_cached
from render.lunar import _lunar_str
from render.pomodoro import pomodoro_state

log = logging.getLogger("render")

WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


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
