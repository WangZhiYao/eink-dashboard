"""Calendar-driven day types, windows, breaks, and date overrides.

The calendar file (CALENDAR_FILE) is the single source of truth for all
time/schedule behavior: per-day-type render windows, meal breaks, rest-day
rendering (simplified screen + optional image), and date overrides
(holidays, makeup workdays, alternating Saturdays...). Any country's
holidays can be expressed by editing the file — nothing is hardcoded here.
"""
import json
import re
from dataclasses import dataclass
from datetime import date

_HHMM_RE = re.compile(r"\d{1,2}:\d{2}")


@dataclass(frozen=True)
class Break:
    start: int          # 当日分钟数
    end: int
    label: str
    end_hm: str         # "HH:MM"


@dataclass(frozen=True)
class DayType:
    type_name: str
    name: str | None = None
    start: int | None = None     # 窗口起点（当日分钟数）；rest 日为 None
    end: int | None = None       # 窗口终点（不含）
    simple: bool = False         # 渲染简化休息画面
    render_at: int | None = None # rest 日首次渲染时刻（分钟数）
    image: str | None = None     # 休息画面图片 URL


def _hhmm_to_min(s: str, idx: int) -> int:
    if not _HHMM_RE.fullmatch(s):
        raise ValueError(f"时间格式非法 #{idx + 1}: {s!r}（需 HH:MM）")
    h, m = int(s[:s.index(":")]), int(s[s.index(":") + 1:])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"时间越界 #{idx + 1}: {s!r}")
    return h * 60 + m


def _parse_breaks(breaks) -> list[Break]:
    """校验结构化 breaks 列表 → 按 start 升序的 [Break, ...]。任一不满足抛 ValueError。"""
    out = []
    for i, item in enumerate(breaks or []):
        if not isinstance(item, dict):
            raise ValueError(f"breaks 条目 #{i + 1} 必须是对象: {item!r}")
        start_s, end_s, label = item.get("start"), item.get("end"), item.get("label")
        if not isinstance(start_s, str) or not isinstance(end_s, str) \
                or not isinstance(label, str) or not label.strip():
            raise ValueError(f"breaks 条目 #{i + 1} 需要 start/end/label 字符串: {item!r}")
        start = _hhmm_to_min(start_s.strip(), i)
        end = _hhmm_to_min(end_s.strip(), i)
        if start >= end:
            raise ValueError(f"breaks 条目 #{i + 1} 起始需早于结束: {item!r}")
        out.append(Break(start, end, label.strip(), f"{end // 60:02d}:{end % 60:02d}"))
    out.sort(key=lambda b: b.start)
    for i in range(1, len(out)):
        if out[i].start < out[i - 1].end:
            raise ValueError(f"breaks 窗口重叠: {out[i - 1].label} 与 {out[i].label}")
    return out


class Calendar:
    def __init__(self, data: dict):
        if not isinstance(data, dict):
            raise ValueError("日历数据必须是 JSON 对象")
        self.render_interval_min = self._int(data, "render_interval_min", 5, 1, 59)
        self.weather_cache_min = self._int(data, "weather_cache_min", 30, 1, 24 * 60)
        self.breaks = _parse_breaks(data.get("breaks"))
        self._weekends = set(self._weekends_list(data.get("weekends", [5, 6])))
        types = data.get("types") or {}
        if not isinstance(types, dict):
            raise ValueError("types 必须是对象")
        self._types = {k: self._parse_type(k, v) for k, v in types.items()}
        # 内置默认（types 显式配置时覆盖之）
        self._types.setdefault("workday", {"start": 540, "end": 1260,
                                           "simple": False, "render_at": None, "image": None})
        self._types.setdefault("rest", {"start": None, "end": None,
                                        "simple": True, "render_at": 540, "image": None})
        overrides = data.get("overrides") or {}
        if not isinstance(overrides, dict):
            raise ValueError("overrides 必须是对象")
        self._overrides = {}
        for ds, val in overrides.items():
            d = date.fromisoformat(ds)          # 非法日期直接 ValueError
            if not isinstance(val, dict) or not isinstance(val.get("type"), str):
                raise ValueError(f"override {ds} 需要对象且含 type 字符串: {val!r}")
            if val["type"] not in self._types:
                raise ValueError(f"override {ds} 引用了不存在的类型: {val['type']!r}")
            name, image = val.get("name"), val.get("image")
            if name is not None and not isinstance(name, str):
                raise ValueError(f"override {ds} 的 name 必须是字符串")
            if image is not None and not isinstance(image, str):
                raise ValueError(f"override {ds} 的 image 必须是字符串")
            self._overrides[d] = (val["type"], name, image)

    @classmethod
    def load(cls, path: str) -> "Calendar":
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls(data)

    @staticmethod
    def _int(data, key, default, lo, hi) -> int:
        v = data.get(key, default)
        if not isinstance(v, int) or isinstance(v, bool) or not (lo <= v <= hi):
            raise ValueError(f"{key} 必须是 {lo}-{hi} 的整数")
        return v

    @staticmethod
    def _weekends_list(v):
        if not isinstance(v, list) or not v:
            raise ValueError("weekends 必须是非空数组")
        out = []
        for x in v:
            if not isinstance(x, int) or isinstance(x, bool) or not (0 <= x <= 6):
                raise ValueError(f"weekends 元素必须是 0-6 的整数: {x!r}")
            out.append(x)
        return out

    @staticmethod
    def _parse_type(name, v) -> dict:
        if not isinstance(v, dict):
            raise ValueError(f"types.{name} 必须是对象")
        cfg = {"start": None, "end": None, "simple": False, "render_at": None, "image": None}
        if "start" in v or "end" in v:
            if not isinstance(v.get("start"), int) or not isinstance(v.get("end"), int):
                raise ValueError(f"types.{name} 需要整数 start/end 小时")
            start, end = v["start"], v["end"]
            if not (0 <= start <= 23 and 0 <= end <= 23 and start < end):
                raise ValueError(f"types.{name} 窗口非法: {start}-{end}")
            cfg["start"], cfg["end"] = start * 60, end * 60
        if "simple" in v:
            if not isinstance(v["simple"], bool):
                raise ValueError(f"types.{name}.simple 必须是布尔")
            cfg["simple"] = v["simple"]
        if "render_at" in v:
            if not isinstance(v["render_at"], str):
                raise ValueError(f"types.{name}.render_at 必须是 HH:MM 字符串")
            cfg["render_at"] = _hhmm_to_min(v["render_at"], 0)
        if "image" in v:
            if not isinstance(v["image"], str):
                raise ValueError(f"types.{name}.image 必须是字符串")
            cfg["image"] = v["image"]
        return cfg

    def day_type(self, d: date) -> DayType:
        ov = self._overrides.get(d)
        if ov is not None:
            t, name, image = ov
            cfg = self._types[t]
            return DayType(type_name=t, name=name, start=cfg["start"], end=cfg["end"],
                           simple=cfg["simple"], render_at=cfg["render_at"],
                           image=image or cfg["image"])
        # weekends 优先于 friday：用户把周五配进 weekends（如中东）时周五按休息日
        if d.weekday() in self._weekends:
            cfg = self._types["rest"]
            return DayType(type_name="rest", start=None, end=None, simple=True,
                           render_at=cfg["render_at"], image=cfg["image"])
        if d.weekday() == 4:                       # Friday
            cfg = self._types["friday"] if "friday" in self._types else self._types["workday"]
            return DayType(type_name="friday", start=cfg["start"], end=cfg["end"],
                           simple=cfg["simple"], render_at=cfg["render_at"], image=cfg["image"])
        cfg = self._types["workday"]
        return DayType(type_name="workday", start=cfg["start"], end=cfg["end"],
                       simple=cfg["simple"], render_at=cfg["render_at"], image=cfg["image"])


from config import settings

calendar = Calendar.load(settings.calendar_file)
