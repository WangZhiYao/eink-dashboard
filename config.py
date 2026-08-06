import re
from collections import namedtuple

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Break = namedtuple("Break", "start end label end_hm")
# start/end: 当日分钟数(int)；label/end_hm: 字符串。按 start 升序。


def _hhmm_to_min(s: str, idx: int) -> int:
    if not re.fullmatch(r"\d{1,2}:\d{2}", s):
        raise ValueError(f"breaks 条目 #{idx + 1} 非法时间: {s!r}")
    h, m = int(s[:s.index(":")]), int(s[s.index(":") + 1:])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"breaks 条目 #{idx + 1} 时间越界: {s!r}")
    return h * 60 + m


def _parse_breaks(s: str) -> list:
    """解析 'HH:MM-HH:MM=标签,...' → 按起始升序的 [Break(start_min, end_min, label, end_hm), ...]。

    校验：每条格式合法、标签非空、start < end、窗口不重叠。任一不满足抛 ValueError
    （pydantic 会包装成 ValidationError，启动早失败）。
    """
    windows = []
    for i, raw in enumerate(s.split(",")):
        item = raw.strip()
        if not item:
            continue
        if "=" not in item:
            raise ValueError(f"breaks 条目 #{i + 1} 缺少 '=': {item!r}")
        window_str, label = item.split("=", 1)
        label = label.strip()
        if not label:
            raise ValueError(f"breaks 条目 #{i + 1} 标签为空: {item!r}")
        if "-" not in window_str:
            raise ValueError(f"breaks 条目 #{i + 1} 时间格式错误: {window_str!r}")
        start_s, end_s = window_str.split("-", 1)
        start = _hhmm_to_min(start_s.strip(), i)
        end = _hhmm_to_min(end_s.strip(), i)
        if start >= end:
            raise ValueError(f"breaks 条目 #{i + 1} 起始需早于结束: {item!r}")
        end_hm = f"{end // 60:02d}:{end % 60:02d}"
        windows.append(Break(start, end, label, end_hm))
    windows.sort(key=lambda b: b.start)
    for i in range(1, len(windows)):
        if windows[i].start < windows[i - 1].end:
            raise ValueError(
                f"breaks 窗口重叠: {windows[i - 1].label} 与 {windows[i].label}")
    return windows


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    sensecraft_device_id: str
    sensecraft_api_key: str
    qweather_host: str
    qweather_api_key: str
    qweather_location: str = "120.16,30.29"
    render_interval_min: int = Field(5, ge=1, le=59)      # daytime refresh rate (minutes); SenseCraft widget should match
    weather_cache_min: int = 30       # cache QWeather responses for this many minutes
    pomodoro_start: int = Field(9, ge=1, le=23)           # Pomodoro + fast-refresh window start hour
    pomodoro_end: int = Field(21, ge=2, le=23)            # Pomodoro + fast-refresh window end hour (exclusive)
    breaks: str = "12:00-13:30=午休,18:00-19:00=晚餐"   # 用餐/休息暂停时段；格式 HH:MM-HH:MM=标签，逗号分隔多条
    break_windows: list = Field(default_factory=list, exclude=True, repr=False)   # 派生字段：_parse_breaks validator 填充，勿直接配
    admin_username: str = "admin"      # Basic-auth username for /todos + /api/todos
    admin_password: str = "changeme"   # Basic-auth password — change before deploy
    tz: str = "Asia/Shanghai"
    todo_db: str = "todos.db"           # SQLite path for todos (volume-mount in Docker)
    log_level: str = "INFO"             # root log level (DEBUG/INFO/WARNING/...); tunable via LOG_LEVEL env

    @model_validator(mode="after")
    def _pomodoro_window_is_valid(self) -> "Settings":
        # Guards the cron expressions built in app._start_scheduler(): an empty or
        # inverted window would produce an invalid cron field and crash scheduler start.
        if self.pomodoro_end <= self.pomodoro_start:
            raise ValueError("pomodoro_end must be greater than pomodoro_start")
        return self

    @model_validator(mode="after")
    def _parse_breaks(self) -> "Settings":
        # 解析并校验 breaks，缓存为派生实例属性 break_windows 供 render 直接读取。
        self.break_windows = _parse_breaks(self.breaks)
        return self


settings = Settings()
