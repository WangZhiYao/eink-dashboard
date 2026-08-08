"""Tests for fetchers.gold — AU99.99 intraday data parsing."""
import pandas as pd
from fetchers.gold import GoldData, fetch_gold_intraday


def _mock_df(prices: list[float], times: list[str] | None = None) -> pd.DataFrame:
    """Build a DataFrame matching ak.spot_quotations_sge output shape."""
    if times is None:
        h, m = 9, 0
        times = []
        for _ in prices:
            times.append(f"{h:02d}:{m:02d}:00")
            m += 1
            if m >= 60:
                h += 1
                m = 0
    return pd.DataFrame({
        "品种": ["Au99.99"] * len(prices),
        "时间": times,
        "现价": [float(p) for p in prices],
        "更新时间": ["2026年08月08日 14:35:00"] * len(prices),
    })


def test_fetch_gold_intraday_parses_prices(monkeypatch):
    """Normal trading day — all fields populated from DataFrame."""
    df = _mock_df([755.0, 756.5, 754.2, 757.0, 760.5])
    monkeypatch.setattr("fetchers.gold.ak.spot_quotations_sge", lambda symbol: df)

    g = fetch_gold_intraday("Au99.99")
    assert g.current == 760.5
    assert g.open == 755.0
    assert g.high == 760.5
    assert g.low == 754.2
    assert len(g.points) == 5
    assert g.points[0] == {"time": "09:00:00", "price": 755.0}
    assert g.points[-1] == {"time": "09:04:00", "price": 760.5}
    assert g.update_time is not None


def test_fetch_gold_intraday_single_point(monkeypatch):
    """Pre-market or just-opened — single data point still parses correctly."""
    df = _mock_df([755.0], times=["09:00:00"])
    monkeypatch.setattr("fetchers.gold.ak.spot_quotations_sge", lambda symbol: df)

    g = fetch_gold_intraday("Au99.99")
    assert g.current == 755.0
    assert g.open == 755.0
    assert g.high == 755.0
    assert g.low == 755.0
    assert len(g.points) == 1


def test_fetch_gold_intraday_empty_df_returns_empty_golddata(monkeypatch):
    """Non-trading day or API issue — empty DataFrame returns GoldData with all None."""
    monkeypatch.setattr("fetchers.gold.ak.spot_quotations_sge", lambda symbol: None)

    g = fetch_gold_intraday("Au99.99")
    assert g.current is None
    assert g.open is None
    assert g.points == []


def test_fetch_gold_intraday_empty_df_returns_empty_golddata_alt(monkeypatch):
    """Empty DataFrame (0 rows) also degrades gracefully."""
    import pandas as pd
    monkeypatch.setattr("fetchers.gold.ak.spot_quotations_sge",
                        lambda symbol: pd.DataFrame())

    g = fetch_gold_intraday("Au99.99")
    assert g.current is None
    assert g.open is None
    assert g.points == []
