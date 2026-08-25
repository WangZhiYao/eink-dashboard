"""模板可画的一切：内联单色 SVG 生成 + Jinja 环境装配。

gold_chart_svg 的 X 轴按交易时间（而非点序）比例映射：夜盘 (20:00→02:30)
占左半、日盘 (09:00→15:30) 占右半 —— Alipay 式分时图。若按点序等距，
~390 个夜盘点会在上午渲染时把日盘挤成一条缝。
"""
from jinja2 import Environment, FileSystemLoader, select_autoescape

_env = Environment(loader=FileSystemLoader("templates"), autoescape=select_autoescape(["html"]))


# Inline monochrome SVGs for common QWeather icon codes (font-independent).
_SVG = {
    "sun": '<circle cx="16" cy="16" r="6"/><g stroke="#0a0a0a" stroke-width="2" stroke-linecap="round">'
           '<line x1="16" y1="3" x2="16" y2="7"/><line x1="16" y1="25" x2="16" y2="29"/>'
           '<line x1="3" y1="16" x2="7" y2="16"/><line x1="25" y1="16" x2="29" y2="16"/>'
           '<line x1="7" y1="7" x2="9.5" y2="9.5"/><line x1="22.5" y1="22.5" x2="25" y2="25"/>'
           '<line x1="25" y1="7" x2="22.5" y2="9.5"/><line x1="9.5" y1="22.5" x2="7" y2="25"/></g>',
    "cloud": '<path d="M9 20a5 5 0 0 1 .6-9.98A6 6 0 0 1 21 12.5a4 4 0 0 1-.5 7.5z"/>',
    "rain": '<path d="M9 18a5 5 0 0 1 .6-9.98A6 6 0 0 1 21 10.5a4 4 0 0 1-.5 7.5z"/>'
             '<g stroke="#0a0a0a" stroke-width="2" stroke-linecap="round">'
             '<line x1="11" y1="23" x2="10" y2="27"/><line x1="17" y1="23" x2="16" y2="27"/>'
             '<line x1="23" y1="23" x2="22" y2="27"/></g>',
}


def _icon_kind(code: str) -> str:
    c = (code or "").lstrip()
    if not c:
        return "cloud"
    n = int(c) if c.isdigit() else 0
    if n in (100,) or 150 <= n < 200:
        return "sun"
    if 300 <= n < 500:
        return "rain"
    return "cloud"


_PRIO_MARKERS = {"high": "●", "normal": "●", "low": "○"}


def prio_marker(prio: str) -> str:
    """Priority marker glyph for the e-ink dashboard. Shape only distinguishes
    solid vs hollow; color comes from the CSS class (.pmark.normal = gray)."""
    return _PRIO_MARKERS.get(prio, "●")


def gold_chart_svg(points: list, width: int = 166, height: int = 64) -> str:
    """Build an inline monochrome SVG line chart from gold data points.
    Returns an <svg> element with a polyline — no JS, no external deps.

    X axis is proportional to TRADING time, not point index: the night session
    (20:00→02:30) maps to the left half and the day session (09:00→15:30) to
    the right half — an Alipay-style 分时图. With index spacing the ~390 night
    points would crush the day session to a sliver whenever the render happens
    mid-morning.
    """
    if not points:
        return '<svg class="ic" viewBox="0 0 %d %d"><text x="%d" y="%d" text-anchor="middle" font-size="12" fill="#5f5f5f">--</text></svg>' % (width, height, width // 2, height // 2 + 4)

    def _tmin(t: str) -> int:
        return int(t[:2]) * 60 + int(t[3:5])

    # Session timeline in trading minutes: night evening 20:00→24:00 = 0→240,
    # night morning 00:00→02:30 = 240→390, day 09:00→15:30 = 390→780.
    def _trading_min(t: str) -> int:
        m = _tmin(t)
        if m >= 20 * 60:          # evening slice: 20:00→24:00 = 0→240
            return m - 20 * 60
        if m <= 150:              # night tail: 00:00→02:30 = 240→390
            return m + 4 * 60
        return m - 150            # day session: 09:00→15:30 = 390→780

    SPAN = 780                    # total trading minutes
    prices = [p["price"] for p in points]
    lo, hi = min(prices), max(prices)
    if hi == lo:
        hi = lo + 1.0  # avoid zero-range

    # Y scale with 10% padding
    pad = (hi - lo) * 0.1
    y_min, y_max = lo - pad, hi + pad

    # Padding: horizontal prevents label/dot clipping; vertical reserves space
    # below the chart for time labels so the polyline doesn't overlap them.
    pad_x = 10
    pad_y_bottom = 12
    pad_y_top = 6
    chart_w = width - 2 * pad_x
    chart_h = height - pad_y_top - pad_y_bottom

    def _x(t: str) -> float:
        return pad_x + (_trading_min(t) / SPAN) * chart_w

    def _y(price: float) -> float:
        return pad_y_top + chart_h - ((price - y_min) / (y_max - y_min)) * chart_h

    # Downsample: one-per-minute data (700+ points) renders as a blob at ~146px
    # wide. Keep at most one vertex per ~2px: bucket points by trading minute,
    # and within each bucket keep the point furthest in price from the LAST
    # kept vertex — turns survive, flat stretches collapse. First/last points
    # always kept (open / current-price dot).
    max_pts = max(int(chart_w // 2), 8)
    tm_all = [_trading_min(p["time"]) for p in points]
    if len(points) > max_pts and tm_all[-1] > tm_all[0]:
        # Guard: sampling assumes trading-minute-monotonic input (what the
        # fetcher returns). Non-monotonic input (raw clock-order cache fed
        # directly) would collapse the line — skip sampling in that case.
        step = (tm_all[-1] - tm_all[0] + 1) / (max_pts - 1)
        picked = [points[0]]
        i = 1
        for b in range(1, max_pts - 1):
            lo_tm = tm_all[0] + b * step
            hi_tm = lo_tm + step
            bucket = [k for k in range(i, len(points)) if lo_tm <= tm_all[k] < hi_tm]
            if not bucket:
                continue
            ref = _y(picked[-1]["price"])
            best = max(bucket, key=lambda k: abs(_y(points[k]["price"]) - ref))
            picked.append(points[best])
            i = best + 1
        if i < len(points):
            picked.append(points[-1])
        points = picked

    # Build polyline points string
    pts = " ".join(f"{_x(p['time']):.1f},{_y(p['price']):.1f}" for p in points)

    # X-axis: FIXED full trading span (0→780). Labels always render — the
    # chart is an Alipay-style 分时图 where the line grows rightward over
    # the trading day, so ticks exist whether or not data covers them yet.
    mid_x = pad_x + chart_w / 2

    # Session divider at the 02:30/09:00 boundary (trading minute 390).
    divider = (
        f'<line x1="{mid_x:.1f}" y1="{pad_y_top}" x2="{mid_x:.1f}" '
        f'y2="{height - pad_y_bottom}" stroke="#c0c0c0" '
        f'stroke-dasharray="2,2" stroke-width="1"/>'
    )

    # (x, label, text-anchor): ends flush to the chart edge, the 02:30/09:00
    # pair splits around the divider — 02:30 right-aligned left of it,
    # 09:00 left-aligned right of it.
    labels = [
        (pad_x, "20:00", "start"),
        (mid_x - 2, "02:30", "end"),
        (mid_x + 2, "09:00", "start"),
        (width - pad_x, "15:30", "end"),
    ]
    label_html = "".join(
        f'<text x="{x:.1f}" y="{height - 2}" text-anchor="{anchor}" '
        f'font-size="7" fill="#5f5f5f">{label}</text>'
        for x, label, anchor in labels
    )
    # Current price dot at the end
    last_x, last_y = _x(points[-1]["time"]), _y(prices[-1])

    return (
        f'<svg class="ic" viewBox="0 0 {width} {height}" style="width:100%;height:auto;">'
        f'{divider}'
        f'<polyline points="{pts}" fill="none" stroke="#0a0a0a" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/>'
        f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="2.5" fill="#0a0a0a"/>'
        f'{label_html}'
        f'</svg>'
    )


def wx_icon_svg(code: str) -> str:
    body = _SVG.get(_icon_kind(code), _SVG["cloud"])
    return f'<svg class="ic" viewBox="0 0 32 32">{body}</svg>'


def render_html(context: dict) -> str:
    return _env.get_template("dashboard.html").render(**context)


_env.globals["gold_chart_svg"] = gold_chart_svg
_env.globals["wx_icon_svg"] = wx_icon_svg
_env.globals["prio_marker"] = prio_marker
