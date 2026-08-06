import os
import pytest
from pydantic import ValidationError
from config import Settings, Break

def test_settings_read_from_env(monkeypatch):
    monkeypatch.setenv("SENSECRAFT_DEVICE_ID", "123")
    monkeypatch.setenv("SENSECRAFT_API_KEY", "sk_x")
    monkeypatch.setenv("QWEATHER_HOST", "https://h.qweatherapi.com")
    monkeypatch.setenv("QWEATHER_API_KEY", "qk")
    s = Settings()
    assert s.sensecraft_device_id == "123"
    assert s.qweather_location == "120.16,30.29"   # default
    assert s.render_interval_min == 5              # default
    assert s.pomodoro_start == 9 and s.pomodoro_end == 21   # default


def _required_env(monkeypatch):
    for k in ("SENSECRAFT_DEVICE_ID", "SENSECRAFT_API_KEY", "QWEATHER_HOST", "QWEATHER_API_KEY"):
        monkeypatch.setenv(k, "x")


def test_rejects_render_interval_out_of_range(monkeypatch):
    _required_env(monkeypatch)
    with pytest.raises(ValidationError):
        Settings(render_interval_min=0)
    with pytest.raises(ValidationError):
        Settings(render_interval_min=60)


def test_rejects_invalid_pomodoro_window(monkeypatch):
    _required_env(monkeypatch)
    with pytest.raises(ValidationError):
        Settings(pomodoro_start=0)          # start must be >= 1
    with pytest.raises(ValidationError):
        Settings(pomodoro_end=1)            # end must be >= 2
    with pytest.raises(ValidationError):
        Settings(pomodoro_start=10, pomodoro_end=10)   # end must be > start


def test_default_breaks_parses_two_windows(monkeypatch):
    _required_env(monkeypatch)
    s = Settings()
    assert [b.label for b in s.break_windows] == ["午休", "晚餐"]
    lunch, dinner = s.break_windows
    assert lunch == Break(720, 810, "午休", "13:30")     # 12:00–13:30
    assert dinner == Break(1080, 1140, "晚餐", "19:00")  # 18:00–19:00


def test_custom_breaks_parsed(monkeypatch):
    _required_env(monkeypatch)
    s = Settings(breaks="11:45-13:00=饭,18:00-19:30=晚饭")
    assert s.break_windows == [
        Break(705, 780, "饭", "13:00"),
        Break(1080, 1170, "晚饭", "19:30"),
    ]


def test_rejects_invalid_breaks(monkeypatch):
    _required_env(monkeypatch)
    bad = [
        "12:00-13:30",                       # 缺 '='
        "12:00-13:30=",                      # 标签为空
        "25:00-13:30=午休",                  # 非法小时
        "12:00-99:30=午休",                  # 非法分钟
        "13:30-12:00=午休",                  # start >= end
        "12:00-13:30=午休,12:30-13:00=茶",   # 窗口重叠
    ]
    for b in bad:
        with pytest.raises(ValidationError):
            Settings(breaks=b)


def test_empty_breaks_allowed(monkeypatch):
    _required_env(monkeypatch)
    s = Settings(breaks="")
    assert s.break_windows == []


def test_break_outside_pomodoro_window_allowed(monkeypatch):
    # spec: 超出 [pomodoro_start, pomodoro_end) 的窗口不报错（用户自由）
    _required_env(monkeypatch)
    s = Settings(breaks="00:00-01:00=深夜")
    assert s.break_windows == [Break(0, 60, "深夜", "01:00")]
