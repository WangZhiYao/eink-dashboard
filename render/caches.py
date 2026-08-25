"""进程内 TTL 缓存：weather / gold 两路取数的缓存策略（含 stale 回退）。

一个 TTLCache 深模块承载全部行为（命中判断、stale 回退、空数据不回写），
weather / gold 各建一个实例——两个 adapter，seam 成立。

Gold 的 TTL 是独立的 5 分钟 — 不是 weather_cache_min。分时图追踪的是
SGE 的实时交易时段；30 分钟窗口会让展示价滞后最多半小时，而 SGE
还在持续修正进行中的行。
"""
import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from config import settings
from daytypes import calendar
from fetchers import weather
from fetchers import gold as gold_fetcher

log = logging.getLogger("render")

# Gold's own cache TTL — NOT weather_cache_min. The 分时图 tracks a live SGE
# session; a 30-min window left the shown price up to half an hour stale while
# SGE kept correcting its in-progress rows.
GOLD_CACHE_MIN = 5


class TTLCache:
    """单值 TTL 缓存：fresh 内命中直接返回；过期（或 epoch 键变化）后重取，
    取数失败回退 stale 缓存（若有），否则返回 degraded 空值；空数据不回写
    缓存（防止瞬时空响应污染整个时段）。

    Interface:
      fetch      取数函数（无参）
      ttl_sec    新鲜期秒数
      epoch_key  now → 分段键（整点小时 / 交易时段）；键变即视为过期
      degraded   无缓存且取数失败时的降级值
      is_empty   判定取数结果为"空"的谓词；空结果不回写缓存
      clock      单调时钟（默认 time.monotonic；测试注入假时钟）
    """

    def __init__(self, fetch, ttl_sec: float, epoch_key, degraded, is_empty=lambda v: False, clock=time.monotonic):
        self.fetch = fetch
        self.ttl_sec = ttl_sec
        self.epoch_key = epoch_key
        self.degraded = degraded
        self.is_empty = is_empty
        self.clock = clock
        self._data = None
        self._ts = 0.0
        self._epoch = None

    def get(self):
        now = self.clock()
        cur_epoch = self.epoch_key()
        cached = self._data
        if (cached is not None and now - self._ts < self.ttl_sec
                and self._epoch == cur_epoch):
            return cached
        try:
            data = self.fetch()
        except Exception:
            # Transient outage: serve stale cache if we have it, else a degraded
            # (empty) payload so the rest of the dashboard still renders.
            log.warning("fetch failed; serving %s", "stale cache" if cached is not None else "degraded", exc_info=True)
            return cached if cached is not None else self.degraded
        # Don't cache empty data (prevents a transient empty response from
        # poisoning the cache for the rest of the session).
        if self.is_empty(data) and cached is not None:
            log.warning("fetch returned empty; keeping stale cache")
            return cached
        self._data = data
        self._ts = now
        self._epoch = cur_epoch
        return data

    def clear(self) -> None:
        """Drop any cached value (test seam / forced refresh)."""
        self._data = None
        self._ts = 0.0
        self._epoch = None


def _gold_session_key(now: datetime) -> str:
    """Return a cache key that changes at gold trading session boundaries.

    The trading-day view computed by fetch_gold_intraday() changes at:
      02:30 — reference date shifts from yesterday to today
      09:00 — day session opens (fresh data)
      20:00 — night session opens, reference shifts to tomorrow
    """
    hm = now.hour * 60 + now.minute
    if hm < 150:                    # 00:00 – 02:30
        segment = "night-end"
    elif hm < 540:                  # 02:30 – 09:00
        segment = "pre-open"
    elif hm < 1200:                 # 09:00 – 20:00
        segment = "day"
    else:                           # 20:00 – 23:59
        segment = "night-start"
    return f"{now.strftime('%Y-%m-%d')}-{segment}"


def _current_hour() -> int:
    return datetime.now(ZoneInfo(settings.tz)).hour


_weather_cache = TTLCache(
    fetch=lambda: weather.fetch_weather(settings.qweather_host, settings.qweather_api_key, settings.qweather_location),
    ttl_sec=calendar.weather_cache_min * 60,
    epoch_key=lambda: _current_hour(),
    degraded=weather.WeatherData(current={}),
)

_gold_cache = TTLCache(
    fetch=lambda: gold_fetcher.fetch_gold_intraday("Au99.99"),
    ttl_sec=GOLD_CACHE_MIN * 60,
    epoch_key=lambda: _gold_session_key(datetime.now(ZoneInfo(settings.tz))),
    degraded=None,
    is_empty=lambda g: g.current is None,
)


def _fetch_weather_cached() -> weather.WeatherData:
    """Serve cached QWeather data while within weather_cache_min AND the same hour;
    otherwise re-fetch. The same-hour check refreshes at each hour boundary so the
    hourly forecast / current-hour framing stays correct."""
    return _weather_cache.get()


def _fetch_gold_cached() -> gold_fetcher.GoldData | None:
    """Serve cached gold data within GOLD_CACHE_MIN (5 min) and the same
    trading session; otherwise re-fetch. Returns None when no data is
    available (never cached and fetch failed)."""
    return _gold_cache.get()
