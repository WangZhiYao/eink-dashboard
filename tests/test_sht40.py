import httpx
import respx
from fetchers.sht40 import parse_sht40, fetch_sht40, Sht40Data

SAMPLE = {
    "result": {
        "sensor": {"temp": 26.4, "humidity": 42.1},
        "battery": {"level": 87},
    }
}

def test_parse_sht40():
    d = parse_sht40(SAMPLE)
    assert d == Sht40Data(temp=26.4, humidity=42.1, battery=87)

def test_parse_sht40_missing_fields():
    d = parse_sht40({})
    assert d == Sht40Data(temp=None, humidity=None, battery=None)

@respx.mock
def test_fetch_sht40_sends_api_key_header():
    route = respx.get("https://sensecraft-hmi-api.seeed.cc/api/v1/user/device/iot_data/123").mock(
        return_value=httpx.Response(200, json=SAMPLE)
    )
    d = fetch_sht40("123", "sk_secret")
    assert route.calls.last.request.headers["api-key"] == "sk_secret"
    assert d.temp == 26.4 and d.battery == 87
