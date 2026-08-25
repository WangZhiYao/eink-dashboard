"""时钟锚定的 25/5 番茄钟状态机（breaks 为真暂停，从时钟折叠扣除）。"""
from datetime import datetime

from daytypes import calendar  # 模块级单例（Calendar.load(settings.calendar_file)）

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
