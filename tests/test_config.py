import os
import pytest
from pydantic import ValidationError
from config import Settings

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
