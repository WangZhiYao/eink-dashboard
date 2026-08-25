"""渲染包：上下文聚合 → HTML → PNG 的完整管线，及调度入口。

外部接口（app.py / 测试 / preview 所依赖的全部名字）在此重新导出：
  render_now / render_tick      — 调度入口（schedule）
  build_context                 — 上下文聚合（context）
  render_html / render_to_png   — 渲染（svg / png）
  pomodoro_state / gold_chart_svg / wx_icon_svg / prio_marker — 状态与 SVG
  calendar / sht40 / weather / gold_fetcher — 依赖的模块引用（测试 seam）
"""
import logging

from render.caches import (
    GOLD_CACHE_MIN,
    TTLCache,
    _fetch_gold_cached,
    _fetch_weather_cached,
    _gold_cache,
    _gold_session_key,
    _weather_cache,
)
from render.context import WEEKDAYS, _todos_for_dashboard, build_context
from render.lunar import _lunar_str
from render.png import OUT_PATH, _html_to_png, _screenshot, render_to_png
from render.pomodoro import BREAK_MIN, CYCLE_MIN, WORK_MIN, pomodoro_state
from render.schedule import render_now, render_tick
from render.svg import gold_chart_svg, prio_marker, wx_icon_svg, render_html

# 测试 monkeypatch 的模块属性 seam —— 从子模块再导出为包属性
from daytypes import calendar
from fetchers import sht40, weather
from fetchers import gold as gold_fetcher

log = logging.getLogger("render")
