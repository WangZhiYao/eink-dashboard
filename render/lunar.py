"""农历格式化：公历 → 中文农历串（如 '七月初一'）。"""
import lunardate
from datetime import datetime

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
