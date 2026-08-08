"""Pytest bootstrap.

config.Settings is instantiated at import time (config.py: `settings = Settings()`)
with required fields (sensecraft_device_id, etc.) that have no defaults. On a
fresh checkout or CI box without a .env file, `import app` would raise a
ValidationError during collection. Provide dummy values here — before any test
module imports app/render/config — so the suite runs anywhere.

setdefault keeps any value already in the environment, and on the dev machine
the real .env still wins for `python app.py` (this file only affects pytest).
"""
import os
from pathlib import Path

for _key, _dummy in {
    "SENSECRAFT_DEVICE_ID": "test-device",
    "SENSECRAFT_API_KEY": "test-key",
    "QWEATHER_HOST": "https://test.example",
    "QWEATHER_API_KEY": "test-key",
}.items():
    os.environ.setdefault(_key, _dummy)

# 测试必须用受控日历（窗口/breaks 固定）——覆盖 .env 里的真实日历，保证断言确定性
os.environ["CALENDAR_FILE"] = str(Path(__file__).parent / "data" / "calendar.test.json")
