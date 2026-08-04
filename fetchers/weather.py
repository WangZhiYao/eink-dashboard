from dataclasses import dataclass, field
from datetime import datetime
import httpx


@dataclass
class WeatherData:
    current: dict                       # temp, feels_like, humidity, text, icon, wind
    hourly: list[dict] = field(default_factory=list)   # {label,text,temp}
    hi: int | None = None
    lo: int | None = None
    tomorrow_hi: int | None = None
    tomorrow_lo: int | None = None
    aqi: int | None = None
    aqi_category: str | None = None
    pm2p5: float | None = None
    rain_chance: int | None = None       # max precip probability in next 6h (%)
    sunrise: str | None = None
    sunset: str | None = None


def parse_now(data: dict) -> dict:
    n = data.get("now") or {}
    wd = n.get("windDir", "")
    ws = n.get("windScale", "")
    return {
        "temp": _int(n.get("temp")),
        "feels_like": _int(n.get("feelsLike")),
        "humidity": _int(n.get("humidity")),
        "text": n.get("text", ""),
        "icon": n.get("icon", ""),
        "wind": f"{wd}{ws}级" if ws else wd,
    }


def parse_hourly(data: dict) -> list[dict]:
    out = []
    for i, h in enumerate(data.get("hourly") or []):
        label = "现在" if i == 0 else _hour_label(h.get("fxTime", ""))
        out.append({"label": label, "text": h.get("text", ""), "temp": _int(h.get("temp")), "rain": _int(h.get("pop"))})
    return out


def parse_daily(data: dict) -> dict:
    days = data.get("daily") or []
    today = days[0] if days else {}
    tomorrow = days[1] if len(days) > 1 else {}
    return {
        "hi": _int(today.get("tempMax")),
        "lo": _int(today.get("tempMin")),
        "tomorrow_hi": _int(tomorrow.get("tempMax")),
        "tomorrow_lo": _int(tomorrow.get("tempMin")),
        "sunrise": today.get("sunrise"),
        "sunset": today.get("sunset"),
    }


def parse_air(data: dict) -> dict:
    n = data.get("now") or {}
    return {"aqi": _int(n.get("aqi")), "category": n.get("category"), "pm2p5": _float(n.get("pm2p5"))}


def fetch_weather(host: str, api_key: str, location: str, client: httpx.Client | None = None) -> WeatherData:
    base = host.rstrip("/")
    headers = {"X-QW-Api-Key": api_key}
    params = {"location": location, "lang": "zh"}  # QWeather defaults to metric; "unit" is rejected (400) by the qweatherapi.com hosts
    paths = ["/v7/weather/now", "/v7/weather/24h", "/v7/weather/3d", "/v7/air/now"]
    own = client is None
    c = client or httpx.Client(timeout=10.0)
    try:
        jsons = {}
        for p in paths:
            r = c.get(f"{base}{p}", params=params, headers=headers)
            r.raise_for_status()
            jsons[p] = r.json()
        daily = parse_daily(jsons["/v7/weather/3d"])
        air = parse_air(jsons["/v7/air/now"])
        hourly_raw = (jsons["/v7/weather/24h"].get("hourly") or [])[:6]
        pops = [_int(h.get("pop")) for h in hourly_raw]
        rain_chance = max([p for p in pops if p is not None], default=None)
        return WeatherData(
            current=parse_now(jsons["/v7/weather/now"]),
            hourly=parse_hourly(jsons["/v7/weather/24h"]),
            hi=daily["hi"], lo=daily["lo"],
            tomorrow_hi=daily["tomorrow_hi"], tomorrow_lo=daily["tomorrow_lo"],
            aqi=air["aqi"], aqi_category=air["category"], pm2p5=air["pm2p5"],
            rain_chance=rain_chance,
            sunrise=daily["sunrise"], sunset=daily["sunset"],
        )
    finally:
        if own:
            c.close()


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _hour_label(iso: str) -> str:
    # "2026-08-02T13:00+08:00" -> "13时"
    try:
        return datetime.fromisoformat(iso).strftime("%H") + "时"
    except ValueError:
        return iso
