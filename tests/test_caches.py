"""TTLCache 接口级测试：构造注入 fetch / epoch_key / 假时钟，零私有状态访问。

原 test_render.py 里 5 个直接读写 _weather_cache/_gold_cache 私有 dict 的
测试在此重写 —— 同样的行为断言（TTL 命中、epoch 变化、stale 回退、独立
TTL、空数据不回写），但全部通过公开接口 get()/clear() 驱动。
"""
from fetchers.weather import WeatherData
from fetchers.gold import GoldData
from render.caches import GOLD_CACHE_MIN, TTLCache, _gold_session_key


class FakeClock:
    """可拨动的单调时钟。"""

    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, sec: float) -> None:
        self.now += sec


def _mk_cache(fetch, *, ttl=60.0, epoch=lambda: "e1", degraded=None,
              is_empty=lambda v: False, clock=None):
    return TTLCache(fetch=fetch, ttl_sec=ttl, epoch_key=epoch, degraded=degraded,
                    is_empty=is_empty, clock=clock or FakeClock())


# ---------------------------------------------------------------------------
# TTL 命中 / 过期 / epoch 变化
# ---------------------------------------------------------------------------

def test_cache_reuses_within_ttl_and_refetches_after_expiry():
    calls = []
    clock = FakeClock()
    cache = _mk_cache(lambda: calls.append(1) or "v", ttl=60.0, clock=clock)

    assert cache.get() == "v"          # fetch
    assert cache.get() == "v"          # served from cache
    assert len(calls) == 1
    clock.advance(61)                  # expire the TTL
    assert cache.get() == "v"          # refetch
    assert len(calls) == 2


def test_cache_refetches_on_epoch_change_despite_fresh_ttl():
    # 跨小时/跨交易时段边界：TTL 未过也必须重取
    calls = []
    epoch = {"v": "e1"}
    cache = _mk_cache(lambda: calls.append(1) or "v", ttl=60.0,
                      epoch=lambda: epoch["v"])

    cache.get()                        # fetch, cached under e1
    cache.get()                        # hit
    assert len(calls) == 1
    epoch["v"] = "e2"                  # simulate crossing an hour boundary
    cache.get()                        # refetch despite fresh TTL
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# stale 回退 / 降级
# ---------------------------------------------------------------------------

def test_failed_refetch_falls_back_to_stale_cache():
    calls = []
    clock = FakeClock()

    def fetch_then_fail():
        calls.append(1)
        return "good" if len(calls) == 1 else (_ for _ in ()).throw(RuntimeError("upstream down"))

    cache = _mk_cache(fetch_then_fail, ttl=60.0, clock=clock)
    assert cache.get() == "good"       # succeeds, populates cache
    clock.advance(61)                  # force a cache miss on next call
    assert cache.get() == "good"       # fetch raises -> stale served, no exception
    assert len(calls) == 2


def test_failed_fetch_with_no_cache_returns_degraded():
    def fail():
        raise RuntimeError("upstream down")

    cache = _mk_cache(fail, ttl=60.0, degraded="DEGRADED")
    assert cache.get() == "DEGRADED"   # never cached + failed -> degraded value


# ---------------------------------------------------------------------------
# 空数据不回写
# ---------------------------------------------------------------------------

def test_empty_fetch_keeps_stale_cache():
    calls = []
    clock = FakeClock()

    def fetch_then_empty():
        calls.append(1)
        return "good" if len(calls) == 1 else "EMPTY"

    cache = _mk_cache(fetch_then_empty, ttl=60.0, clock=clock,
                      is_empty=lambda v: v == "EMPTY")
    assert cache.get() == "good"
    clock.advance(61)
    assert cache.get() == "good"       # empty response must not poison the cache
    assert len(calls) == 2
    cache.clear()
    assert cache.get() == "EMPTY"      # with no cache, empty IS served (gold: None)


# ---------------------------------------------------------------------------
# weather / gold 两个 adapter 实例的行为
# ---------------------------------------------------------------------------

def test_gold_cache_ttl_is_independent_five_minutes(monkeypatch):
    """Gold 的 TTL 是自己的 5 分钟窗口，不是 weather_cache_min（30 分）：
    gold 是实时分时图，必须追踪 SGE 进行中的时段。"""
    import render.caches as caches
    monkeypatch.setattr(caches.weather, "fetch_weather",
                        lambda *a, **k: WeatherData(current={"temp": 28}))
    assert caches._weather_cache.ttl_sec == 30 * 60      # weather_cache_min from test calendar
    assert caches._gold_cache.ttl_sec == GOLD_CACHE_MIN * 60
    assert GOLD_CACHE_MIN == 5


def test_gold_session_key_segments():
    from datetime import datetime
    assert _gold_session_key(datetime(2026, 8, 24, 1, 0)).endswith("night-end")
    assert _gold_session_key(datetime(2026, 8, 24, 5, 0)).endswith("pre-open")
    assert _gold_session_key(datetime(2026, 8, 24, 12, 0)).endswith("day")
    assert _gold_session_key(datetime(2026, 8, 24, 21, 0)).endswith("night-start")
