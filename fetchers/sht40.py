from dataclasses import dataclass
import httpx

API_BASE = "https://sensecraft-hmi-api.seeed.cc/api/v1/user/device/iot_data"


@dataclass
class Sht40Data:
    temp: float | None
    humidity: float | None
    battery: float | None


def parse_sht40(data: dict) -> Sht40Data:
    result = data.get("result") or {}
    sensor = result.get("sensor") or {}
    battery = result.get("battery") or {}
    return Sht40Data(
        temp=sensor.get("temp"),
        humidity=sensor.get("humidity"),
        battery=battery.get("level"),
    )


def fetch_sht40(device_id: str, api_key: str, client: httpx.Client | None = None) -> Sht40Data:
    url = f"{API_BASE}/{device_id}"
    headers = {"api-key": api_key}
    own = client is None
    c = client or httpx.Client(timeout=10.0)
    try:
        r = c.get(url, headers=headers)
        r.raise_for_status()
        return parse_sht40(r.json())
    finally:
        if own:
            c.close()
