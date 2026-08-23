"""Tests for fetchers.gold — AU99.99 trading-day assembly.

The SGE trading day spans midnight: night 20:00→02:30 belongs to the FOLLOWING
trading day, day session 09:00→15:30 belongs to its own calendar date. The
trading day shown is the one owning the newest data, per the API's 更新时间
stamp (whose date part encodes weekend/holiday attribution — a Saturday 02:29
fetch is stamped the upcoming Monday).
"""
import datetime as _dt
import json
from unittest.mock import patch

import pandas as pd
import pytest

from fetchers.gold import (
    GoldData,
    _assemble_trading_days,
    _dedup_by_time,
    _parse_stamp,
    fetch_gold_intraday,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pts(start: str, end: str, base_price: float = 750.0, step: float = 0.1) -> list[dict]:
    """Mock points for a HH:MM–HH:MM range, one per minute."""
    sh, sm = int(start[:2]), int(start[3:4 + 1][:2])
    eh, em = int(end[:2]), int(end[3:5])
    sh, sm, eh, em = int(start[:2]), int(start[3:5]), int(end[:2]), int(end[3:5])
    out = []
    price = base_price
    while (sh, sm) <= (eh, em):
        out.append({"time": f"{sh:02d}:{sm:02d}:00", "price": round(price, 2)})
        sm += 1
        if sm >= 60:
            sh, sm = sh + 1, 0
        price += step
    return out


def _make_df(points: list[dict], stamp: str = "2026年08月11日 10:00:00") -> pd.DataFrame:
    if not points:
        return pd.DataFrame()
    times = [_dt.time(int(p["time"][:2]), int(p["time"][3:5]), int(p["time"][6:8]))
             for p in points]
    return pd.DataFrame({
        "品种": ["Au99.99"] * len(points),
        "时间": times,
        "现价": [p["price"] for p in points],
        "更新时间": [stamp] * len(points),
    })


# ---------------------------------------------------------------------------
# Stamp parsing
# ---------------------------------------------------------------------------

def test_parse_stamp():
    assert _parse_stamp("2026年08月17日 02:29:54") == "2026-08-17"
    assert _parse_stamp("2026年8月1日 09:00:00") == "2026-08-01"
    assert _parse_stamp("") is None
    assert _parse_stamp(None) is None
    assert _parse_stamp("garbage") is None


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------

def test_dedup_by_time():
    pts = [{"time": "20:00:00", "price": 100.0},
           {"time": "20:01:00", "price": 101.0},
           {"time": "20:00:00", "price": 102.0}]   # duplicate, newer price
    out = _dedup_by_time(pts)
    assert len(out) == 2
    assert out[0]["price"] == 102.0                # last occurrence wins
    assert out[1]["time"] == "20:01:00"


# ---------------------------------------------------------------------------
# Trading-day assembly
# ---------------------------------------------------------------------------

class TestAssembleTradingDays:
    def _run(self, days):
        return _assemble_trading_days(days)

    def test_simple_weekday_flow(self):
        """Wed evening + Thu morning+day assemble into Thu's trading day."""
        days = {
            "2026-08-12": _pts("20:00", "23:59", 950.0),               # Wed eve
            "2026-08-13": _pts("00:00", "02:30", 952.0) + _pts("09:00", "15:30", 954.0),
        }
        td_map, pending = self._run(days)
        assert "2026-08-13" in td_map
        assert pending == []
        pts = td_map["2026-08-13"]
        assert pts[0]["time"] == "20:00:00"          # night opens the view
        assert pts[-1]["time"] == "15:30:00"         # day session closes it

    def test_evening_starts_pending_night(self):
        """A day with only evening points leaves a pending night."""
        days = {"2026-08-11": _pts("20:00", "21:00", 950.0)}
        td_map, pending = self._run(days)
        assert td_map == {}
        assert len(pending) == 61
        assert pending[0]["time"] == "20:00:00"

    def test_weekend_evening_belongs_to_monday(self):
        """Fri evening + Sat/Sun morning slices feed Monday's trading day."""
        days = {
            "2026-08-14": _pts("09:00", "15:30", 940.0) + _pts("20:00", "23:59", 942.0),
            "2026-08-15": _pts("00:00", "02:30", 943.0),               # Sat morn
        }
        td_map, pending = self._run(days)
        assert "2026-08-14" in td_map                  # Fri trading day complete
        assert pending[0]["time"] == "20:00:00"        # Fri eve, waiting for Mon
        # Simulate stamp saying Monday owns this night
        td_map["2026-08-17"] = pending
        assert td_map["2026-08-17"][0]["price"] == 942.0

    def test_duplicate_weekend_slices_dedup(self):
        """The endpoint repeats finished night rows on Sat and Sun fetches."""
        days = {
            "2026-08-14": _pts("20:00", "23:59", 942.0),
            "2026-08-15": _pts("00:00", "02:30", 943.0),
            "2026-08-16": _pts("00:00", "02:30", 943.0),               # same rows again
        }
        _, pending = self._run(days)
        times = [p["time"] for p in pending]
        assert len(times) == len(set(times))          # no duplicate minutes
        assert times[0] == "20:00:00" and times[-1] == "02:30:00"

    def test_open_price_prefers_day_session(self):
        """Open comes from day session's first point when present."""
        days = {
            "2026-08-12": _pts("20:00", "23:59", 950.0),
            "2026-08-13": _pts("00:00", "02:30", 952.0) + _pts("09:00", "15:30", 954.0),
        }
        td_map, _ = self._run(days)
        pts = td_map["2026-08-13"]
        day_prices = [p["price"] for p in pts if "09:00:00" <= p["time"] <= "15:30:00"]
        assert day_prices[0] == 954.0


# ---------------------------------------------------------------------------
# fetch_gold_intraday — full flow with cache + stamp
# ---------------------------------------------------------------------------

class TestFetchTradingDay:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, tmp_path):
        self.cache_file = str(tmp_path / "gold_cache.json")
        monkeypatch.setattr("fetchers.gold.GOLD_CACHE_FILE", self.cache_file)
        self.mp = monkeypatch

    def _mock_now(self, dt: _dt.datetime):
        class FakeDateTime(_dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return dt
        self.mp.setattr("fetchers.gold.datetime", FakeDateTime)

    def _mock_ak(self, points, stamp):
        df = _make_df(points, stamp) if points else pd.DataFrame()
        self.mp.setattr("fetchers.gold.ak.spot_quotations_sge", lambda symbol: df)

    def test_day_session_stamped_today(self):
        """Thursday 10:00 fetch, stamped Thursday — night+day of today shown."""
        self._mock_now(_dt.datetime(2026, 8, 13, 10, 0))
        # Wed evening cached from earlier fetch
        with open(self.cache_file, "w", encoding="utf-8") as f:
            json.dump({"days": {"2026-08-12": _pts("20:00", "23:59", 950.0)},
                       "last_stamp": None}, f)
        self._mock_ak(
            _pts("00:00", "02:30", 952.0) + _pts("09:00", "10:00", 954.0),
            stamp="2026年08月13日 10:00:00",
        )
        g = fetch_gold_intraday("Au99.99")
        assert g.points[0]["time"] == "20:00:00"      # cached Wed evening
        assert g.points[-1]["time"] == "10:00:00"     # live day session
        assert g.open == 954.0                        # day-session open
        assert g.current == g.points[-1]["price"]

    def test_evening_rolls_to_tomorrow(self):
        """Thursday 22:00 fetch stamped Friday — the view rolls to Friday's
        trading day, which so far is just tonight's night session (its evening
        slice). Thursday's finished day is NOT spliced in: the display shows
        one trading day (evening → morning → day), per the module docstring."""
        self._mock_now(_dt.datetime(2026, 8, 13, 22, 0))
        self._mock_ak(
            _pts("00:00", "02:30", 950.0) + _pts("09:00", "15:30", 952.0)
            + _pts("20:00", "22:00", 956.0),
            stamp="2026年08月14日 22:00:00",
        )
        g = fetch_gold_intraday("Au99.99")
        times = [p["time"] for p in g.points]
        assert times[0] == "20:00:00"     # tonight's night opens Friday's day
        assert times[-1] == "22:00:00"    # and is all Friday has so far
        assert g.current == g.points[-1]["price"]

    def test_saturday_morning_stamped_monday(self):
        """Sat 01:00 fetch stamped Monday — shows Fri eve + Sat morn night."""
        self._mock_now(_dt.datetime(2026, 8, 15, 1, 0))
        # Friday's full calendar day already cached
        with open(self.cache_file, "w", encoding="utf-8") as f:
            json.dump({"days": {"2026-08-14": _pts("09:00", "15:30", 940.0)
                                + _pts("20:00", "23:59", 942.0)},
                       "last_stamp": None}, f)
        self._mock_ak(
            _pts("00:00", "01:00", 943.0),
            stamp="2026年08月17日 01:00:00",
        )
        g = fetch_gold_intraday("Au99.99")
        # Friday's trading day exists, but newest data is stamped Monday —
        # the pending night (Fri eve + Sat morn) is Monday's night.
        times = [p["time"] for p in g.points]
        assert times[0] == "20:00:00"
        assert times[-1] == "01:00:00"
        assert g.current == g.points[-1]["price"]

    def test_empty_fetch_keeps_stamp_and_serves_assembled(self):
        """Network died — stale stamp still selects the last complete day."""
        self._mock_now(_dt.datetime(2026, 8, 13, 16, 0))
        with open(self.cache_file, "w", encoding="utf-8") as f:
            json.dump({"days": {"2026-08-12": _pts("20:00", "23:59", 950.0),
                                "2026-08-13": _pts("00:00", "02:30", 952.0)
                                + _pts("09:00", "15:30", 954.0)},
                       "last_stamp": "2026-08-13"}, f)
        self._mock_ak(None, stamp=None)
        g = fetch_gold_intraday("Au99.99")
        assert g.points[0]["time"] == "20:00:00"
        assert g.points[-1]["time"] == "15:30:00"     # full Thursday
        assert g.update_time is None                  # no fresh stamp this call

    def test_no_data_anywhere_returns_empty(self):
        """Nothing fetched, nothing cached → GoldData() all-None."""
        self._mock_now(_dt.datetime(2026, 8, 13, 10, 0))
        self._mock_ak(None, stamp=None)
        g = fetch_gold_intraday("Au99.99")
        assert g.current is None
        assert g.points == []

    def test_akshare_exception_returns_empty(self):
        self._mock_now(_dt.datetime(2026, 8, 13, 10, 0))
        self.mp.setattr(
            "fetchers.gold.ak.spot_quotations_sge",
            lambda symbol: (_ for _ in ()).throw(RuntimeError("network error")),
        )
        g = fetch_gold_intraday("Au99.99")
        assert g.current is None
        assert g.points == []

    def test_legacy_cache_format_still_loads(self):
        """Old {date: [points]} top-level format upgrades in place."""
        self._mock_now(_dt.datetime(2026, 8, 13, 16, 0))
        with open(self.cache_file, "w", encoding="utf-8") as f:
            json.dump({"2026-08-13": _pts("09:00", "15:30", 954.0)}, f)
        self._mock_ak(None, stamp=None)
        g = fetch_gold_intraday("Au99.99")
        assert g.points[0]["time"] == "09:00:00"
        # _pts is inclusive: 09:00–15:30 spans 391 points, last = base + 390*step
        assert g.current == pytest.approx(954.0 + 390 * 0.1)

    def test_stats_computed_from_assembled(self):
        self._mock_now(_dt.datetime(2026, 8, 13, 14, 0))
        with open(self.cache_file, "w", encoding="utf-8") as f:
            json.dump({"days": {"2026-08-12": _pts("20:00", "23:59", 950.0)},
                       "last_stamp": None}, f)
        self._mock_ak(
            _pts("00:00", "02:30", 948.0) + _pts("09:00", "14:00", 960.0),
            stamp="2026年08月13日 14:00:00",
        )
        g = fetch_gold_intraday("Au99.99")
        assert g.low == pytest.approx(948.0)
        # _pts is inclusive: 09:00–14:00 spans 301 points, top = base + 300*step
        assert g.high == pytest.approx(960.0 + 300 * 0.1)
        assert g.current == g.high
        assert g.open == 960.0

    def test_cache_file_pruned_to_max_days(self):
        """Save keeps only GOLD_CACHE_MAX_DAYS most recent calendar days."""
        from fetchers.gold import GOLD_CACHE_MAX_DAYS, _load_gold_cache, _save_gold_cache
        days = {f"2026-08-{d:02d}": _pts("09:00", "09:01", 950.0)
                for d in range(1, 12)}
        _save_gold_cache({"days": days, "last_stamp": "2026-08-11"})
        loaded = _load_gold_cache()
        assert len(loaded["days"]) == GOLD_CACHE_MAX_DAYS
        assert "2026-08-11" in loaded["days"]
        assert "2026-08-05" not in loaded["days"]
        assert loaded["last_stamp"] == "2026-08-11"

    def test_stamp_unknown_uses_latest_assembled(self):
        """No stamp and no pending night → show most recent complete day."""
        self._mock_now(_dt.datetime(2026, 8, 13, 16, 0))
        with open(self.cache_file, "w", encoding="utf-8") as f:
            json.dump({"days": {"2026-08-11": _pts("09:00", "15:30", 940.0),
                                "2026-08-12": _pts("09:00", "15:30", 950.0)},
                       "last_stamp": None}, f)
        self._mock_ak(None, stamp=None)
        g = fetch_gold_intraday("Au99.99")
        assert g.open == 950.0                         # Aug 12 (latest) served
