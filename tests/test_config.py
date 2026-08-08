import pytest
from pydantic import ValidationError
from config import Settings


def test_settings_read_from_env(monkeypatch):
    monkeypatch.setenv("SENSECRAFT_DEVICE_ID", "123")
    monkeypatch.setenv("SENSECRAFT_API_KEY", "sk_x")
    monkeypatch.setenv("QWEATHER_HOST", "https://h.qweatherapi.com")
    monkeypatch.setenv("QWEATHER_API_KEY", "qk")
    monkeypatch.setenv("CALENDAR_FILE", "calendar.json")
    s = Settings()
    assert s.sensecraft_device_id == "123"
    assert s.calendar_file == "calendar.json"
    assert s.qweather_location == "120.16,30.29"   # default
    assert s.tz == "Asia/Shanghai"                 # default


def _required_env(monkeypatch):
    for k in ("SENSECRAFT_DEVICE_ID", "SENSECRAFT_API_KEY",
              "QWEATHER_HOST", "QWEATHER_API_KEY", "CALENDAR_FILE"):
        monkeypatch.setenv(k, "x")


def test_requires_calendar_file(monkeypatch):
    for k in ("SENSECRAFT_DEVICE_ID", "SENSECRAFT_API_KEY", "QWEATHER_HOST", "QWEATHER_API_KEY"):
        monkeypatch.setenv(k, "x")
    monkeypatch.delenv("CALENDAR_FILE", raising=False)
    with pytest.raises(ValidationError):
        Settings()
