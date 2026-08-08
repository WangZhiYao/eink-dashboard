"""AU99.99 (Shanghai Gold Exchange) intraday data via AKShare."""
from dataclasses import dataclass, field
import logging

import akshare as ak

log = logging.getLogger("fetchers.gold")


@dataclass
class GoldData:
    current: float | None = None      # 最新价
    open: float | None = None         # 开盘价（当日第一个数据点）
    high: float | None = None         # 日内最高
    low: float | None = None          # 日内最低
    points: list[dict] = field(default_factory=list)  # [{"time": "09:00:00", "price": 755.0}, ...]
    update_time: str | None = None    # 数据更新时间 (e.g. "2026年08月08日 14:35:00")


def fetch_gold_intraday(symbol: str = "Au99.99") -> GoldData:
    """Fetch today's intraday minute data for a Shanghai Gold Exchange symbol."""
    df = ak.spot_quotations_sge(symbol=symbol)
    if df is None or df.empty:
        log.warning("gold fetch returned empty DataFrame for %s", symbol)
        return GoldData()

    prices = df["现价"].astype(float)
    return GoldData(
        current=prices.iloc[-1],
        open=prices.iloc[0],
        high=prices.max(),
        low=prices.min(),
        points=[{"time": str(r["时间"]), "price": float(r["现价"])}
                for _, r in df.iterrows()],
        update_time=str(df["更新时间"].iloc[-1]) if "更新时间" in df.columns else None,
    )
