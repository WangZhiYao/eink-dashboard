"""AU99.99 (Shanghai Gold Exchange) intraday data via AKShare.

An SGE trading day spans midnight — this is what an Alipay-style 分时图 shows:
    night session: prev trading evening 20:00 → 02:30 (next calendar day)
    day session:   09:00 → 15:30

So one calendar day of API data mixes slices of up to three trading days.
We persist raw calendar-day points in a JSON cache and segment them by the
exchange rule — the 20:00+ evening slice and the 00:00–02:30 morning slice
form the *night* of the following trading day (weekends included: Friday
evening + Saturday morning belong to Monday). The trading day to display is
taken from the API's own 更新时间 stamp, whose date part already encodes the
weekend/holiday attribution of the newest data (verified: a Tuesday 22:22
fetch is stamped Wednesday; a Saturday 02:29 fetch is stamped Monday).
"""
from dataclasses import dataclass, field
from datetime import datetime
import json
import logging
import os
import re

import akshare as ak

log = logging.getLogger("fetchers.gold")

# File-based cache — persists intraday data across calendar days so the
# evening slice feeding tomorrow's night session survives the midnight rollover.
GOLD_CACHE_FILE = "static/gold_intraday_cache.json"
GOLD_CACHE_MAX_DAYS = 5  # Fri→Mon weekend needs 4; keep one spare

# Session boundaries, minutes since midnight
_MORNING_END = 150                    # 02:30 — night session close
_DAY_START, _DAY_END = 540, 930       # 09:00–15:30 day session
_EVENING_START = 1200                 # 20:00 — night session open

_STAMP_RE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")


@dataclass
class GoldData:
    current: float | None = None      # 最新价
    open: float | None = None         # 开盘价（日盘首个点，夜盘中则为夜盘开盘）
    high: float | None = None         # 日内最高
    low: float | None = None          # 日内最低
    points: list[dict] = field(default_factory=list)  # [{"time": "20:00:00", "price": 755.0}, ...]
    update_time: str | None = None    # 数据更新时间 (e.g. "2026年08月11日 14:35:00")


# ---------------------------------------------------------------------------
# Cache persistence
# ---------------------------------------------------------------------------

def _load_gold_cache() -> dict:
    """Load {"days": {date: [point, ...]}, "last_stamp": str | None}.
    Accepts the legacy {date: [point, ...]} top-level format too."""
    try:
        with open(GOLD_CACHE_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        raw = None
    if isinstance(raw, dict) and "days" in raw:
        return raw
    if isinstance(raw, dict):  # legacy format: {date: [points]}
        return {"days": raw, "last_stamp": None}
    return {"days": {}, "last_stamp": None}


def _save_gold_cache(cache: dict) -> None:
    """Save to disk, pruning to the last GOLD_CACHE_MAX_DAYS calendar days."""
    days = cache.get("days", {})
    keys = sorted(days.keys(), reverse=True)
    pruned = {k: days[k] for k in keys[:GOLD_CACHE_MAX_DAYS]}
    payload = {"days": pruned, "last_stamp": cache.get("last_stamp")}
    os.makedirs(os.path.dirname(GOLD_CACHE_FILE) or ".", exist_ok=True)
    with open(GOLD_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_min(t: str) -> int:
    h, m = int(t[:2]), int(t[3:5])
    return h * 60 + m


def _slice(points: list[dict], lo: int, hi: int) -> list[dict]:
    """Points whose 'time' falls in [lo, hi] minutes since midnight."""
    return [p for p in points if lo <= _to_min(p["time"]) <= hi]


def _parse_stamp(s: str | None) -> str | None:
    """'2026年08月17日 02:29:54' → '2026-08-17' (trading day of the newest data)."""
    if not s:
        return None
    m = _STAMP_RE.search(s)
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return f"{y:04d}-{mo:02d}-{d:02d}"


def _dedup_by_time(points: list[dict]) -> list[dict]:
    """Drop duplicate 'time' entries, keeping the LAST occurrence's price at
    the FIRST appearance's position (stable order). The SGE endpoint serves
    the same finished night-session rows on both weekend days, so Sat and Sun
    calendar slices can contain copies of the same minutes. Order must stay
    stable — callers rely on it for chronological plotting and current-price
    (points are evening→morning→day, NOT clock-sorted, so a plain sorted()
    would move the evening slice behind the morning tail)."""
    idx: dict[str, int] = {}
    out: list[dict] = []
    for p in points:
        t = p["time"]
        if t in idx:
            out[idx[t]] = p          # later value wins, order slot unchanged
        else:
            idx[t] = len(out)
            out.append(p)
    return out


def _assemble_trading_days(days: dict[str, list[dict]]) -> tuple[dict[str, list[dict]], list[dict]]:
    """Segment calendar-day slices into per-trading-day point lists.

    Walk cached calendar days in order. Morning (00:00–02:30) points are the
    tail of the night session opened the previous evening; when a day session
    (09:00–15:30) appears, the accumulated night belongs to that trading day.
    Evening (20:00+) points start the *next* trading day's night. Any trailing
    night (no day session yet) is returned separately — the caller attaches it
    to the trading day named by the API stamp.
    """
    td_map: dict[str, list[dict]] = {}
    night: list[dict] = []
    for d in sorted(days):
        pts = days[d]
        night = _dedup_by_time(night + _slice(pts, 0, _MORNING_END))
        day = _slice(pts, _DAY_START, _DAY_END)
        if day:
            td_map[d] = _dedup_by_time(night + day)
            night = []
        night = _dedup_by_time(night + _slice(pts, _EVENING_START, 24 * 60 - 1))
    return td_map, night


# ---------------------------------------------------------------------------
# Main fetch
# ---------------------------------------------------------------------------

def fetch_gold_intraday(symbol: str = "Au99.99") -> GoldData:
    """Fetch and assemble the current trading day's intraday data.

    The displayed trading day is the one owning the newest data (per the API
    stamp): during the day session that's today; from 20:00 on it rolls to
    tomorrow (tonight's night is tomorrow's trading day); over a weekend it
    is the upcoming Monday. Points are returned in chronological order:
    evening → morning → day session.
    """
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")

    fresh: list[dict] = []
    stamp: str | None = None
    update_time: str | None = None
    try:
        df = ak.spot_quotations_sge(symbol=symbol)
    except Exception:
        log.warning("gold fetch failed for %s", symbol, exc_info=True)
        df = None
    if df is not None and not df.empty:
        fresh = [{"time": str(r["时间"]), "price": float(r["现价"])}
                 for _, r in df.iterrows()]
        if "更新时间" in df.columns:
            update_time = str(df["更新时间"].iloc[-1])
            stamp = _parse_stamp(update_time)

    cache = _load_gold_cache()
    if fresh:
        cache.setdefault("days", {})[today_str] = fresh
        if stamp:
            cache["last_stamp"] = stamp
        _save_gold_cache(cache)
    # A failed/empty fetch keeps serving the last good stamp (and cached days).
    stamp = stamp or cache.get("last_stamp")

    td_map, pending_night = _assemble_trading_days(cache.get("days", {}))
    if pending_night and stamp:
        # Night in progress — belongs to the stamped (upcoming) trading day.
        td_map[stamp] = td_map.get(stamp, []) + pending_night

    # Display the trading day owning the newest data; fall back to the most
    # recent assembled day when the stamp is unknown.
    if stamp and stamp in td_map:
        points = td_map[stamp]
    elif td_map:
        points = td_map[max(td_map)]
    else:
        points = []

    if not points:
        return GoldData()

    prices = [p["price"] for p in points]
    day_prices = [p["price"] for p in points
                  if _DAY_START <= _to_min(p["time"]) <= _DAY_END]
    return GoldData(
        current=prices[-1],
        open=day_prices[0] if day_prices else prices[0],
        high=max(prices),
        low=min(prices),
        points=points,
        update_time=update_time,
    )
