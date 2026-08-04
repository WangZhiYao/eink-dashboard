import httpx
import respx
from fetchers.weather import (
    parse_now, parse_hourly, parse_daily, parse_air, fetch_weather, WeatherData,
)

def test_parse_now():
    assert parse_now({"now": {"temp": "28", "feelsLike": "30", "humidity": "60",
                              "text": "多云", "icon": "104", "windDir": "东北", "windScale": "2"}}) == {
        "temp": 28, "feels_like": 30, "humidity": 60, "text": "多云",
        "icon": "104", "wind": "东北2级",
    }

def test_parse_hourly_labels_first_as_now():
    hs = parse_hourly({"hourly": [
        {"fxTime": "2026-08-02T11:00+08:00", "temp": "28", "text": "多云", "pop": "10"},
        {"fxTime": "2026-08-02T13:00+08:00", "temp": "30", "text": "晴", "pop": "0"},
    ]})
    assert hs[0] == {"label": "现在", "text": "多云", "temp": 28, "rain": 10}
    assert hs[1] == {"label": "13时", "text": "晴", "temp": 30, "rain": 0}

def test_parse_daily():
    d = parse_daily({"daily": [{"tempMax": "29", "tempMin": "21", "sunrise": "05:42", "sunset": "19:08"},
                               {"tempMax": "30", "tempMin": "22"}]})
    assert d == {"hi": 29, "lo": 21, "tomorrow_hi": 30, "tomorrow_lo": 22, "sunrise": "05:42", "sunset": "19:08"}

def test_parse_air():
    assert parse_air({"now": {"aqi": "45", "category": "优", "pm2p5": "12"}}) == {
        "aqi": 45, "category": "优", "pm2p5": 12,
    }

@respx.mock
def test_fetch_weather_hits_four_endpoints():
    host = "https://h.qweatherapi.com"
    respx.get(f"{host}/v7/weather/now").mock(return_value=httpx.Response(200, json={"now": {"temp": "28", "text": "多云", "icon": "104"}}))
    respx.get(f"{host}/v7/weather/24h").mock(return_value=httpx.Response(200, json={"hourly": [{"fxTime": "2026-08-02T11:00+08:00", "temp": "28", "text": "多云", "pop": "34"}]}))
    respx.get(f"{host}/v7/weather/3d").mock(return_value=httpx.Response(200, json={"daily": [{"tempMax": "29", "tempMin": "21", "sunrise": "05:42", "sunset": "19:08"}]}))
    respx.get(f"{host}/v7/air/now").mock(return_value=httpx.Response(200, json={"now": {"aqi": "45", "category": "优", "pm2p5": "12"}}))
    w = fetch_weather(host, "qk", "120.16,30.29")
    assert isinstance(w, WeatherData)
    assert w.current["temp"] == 28
    assert w.hourly[0]["label"] == "现在"
    assert w.hi == 29 and w.aqi == 45 and w.rain_chance == 34 and w.sunrise == "05:42" and w.sunset == "19:08"
    assert respx.calls.last.request.headers["x-qw-api-key"] == "qk"
