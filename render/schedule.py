"""渲染调度：串行锁 + 按日类型决定渲染窗口的 tick 入口。"""
import logging
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from config import settings
from daytypes import calendar

from render.context import build_context
from render.png import OUT_PATH, render_to_png

log = logging.getLogger("render")

_render_lock = threading.Lock()


def render_now() -> None:
    # Serialize renders: APScheduler fires jobs from a thread pool and they can
    # overlap, but Playwright, the shared weather cache, and the fixed tmp path
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
