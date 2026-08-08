import json
from datetime import date
import pytest
from daytypes import Calendar, Break


def _cal(overrides=None, **kw):
    data = {"overrides": overrides or {}}
    data.update(kw)
    return Calendar(data)


def test_defaults_when_types_missing():
    c = Calendar({})
    assert c.render_interval_min == 5
    assert c.weather_cache_min == 30
    assert c.breaks == []
    dt = c.day_type(date(2026, 8, 3))      # Monday
    assert (dt.type_name, dt.start, dt.end) == ("workday", 540, 1260)
    assert dt.simple is False and dt.image is None
    dt_sat = c.day_type(date(2026, 8, 8))  # Saturday
    assert dt_sat.simple is True and dt_sat.render_at == 540


def test_friday_uses_own_type():
    c = _cal(types={"workday": {"start": 9, "end": 21},
                    "friday": {"start": 9, "end": 18}})
    assert (c.day_type(date(2026, 8, 7)).start, c.day_type(date(2026, 8, 7)).end) == (540, 1080)  # Friday


def test_friday_falls_back_to_workday():
    c = _cal(types={"workday": {"start": 9, "end": 21}})
    assert c.day_type(date(2026, 8, 7)).type_name == "friday"
    assert c.day_type(date(2026, 8, 7)).end == 1260


def test_override_beats_weekday_rule():
    c = _cal(overrides={"2026-08-08": {"type": "workday", "name": "大周"}})
    dt = c.day_type(date(2026, 8, 8))     # Saturday
    assert dt.type_name == "workday" and dt.name == "大周"
    assert dt.start == 540                 # inherits workday window


def test_override_rest_holiday():
    c = _cal(overrides={"2026-10-01": {"type": "rest", "name": "国庆节"}})
    dt = c.day_type(date(2026, 10, 1))    # Thursday
    assert dt.simple is True and dt.name == "国庆节"


def test_override_image_overrides_type_image():
    c = _cal(types={"rest": {"simple": True, "image": "https://default.png"}},
             overrides={"2026-10-01": {"type": "rest", "name": "国庆节", "image": "https://oct1.png"}})
    assert c.day_type(date(2026, 10, 1)).image == "https://oct1.png"
    assert c.day_type(date(2026, 8, 8)).image == "https://default.png"


def test_custom_weekends():
    c = _cal(weekends=[4, 5])             # e.g. Middle East: Fri(4)+Sat(5) rest
    assert c.day_type(date(2026, 8, 7)).simple is True      # Friday rest
    assert c.day_type(date(2026, 8, 8)).simple is True      # Saturday rest
    assert c.day_type(date(2026, 8, 9)).type_name == "workday"  # Sunday works


def test_breaks_parsed_and_sorted():
    c = _cal(breaks=[{"start": "18:00", "end": "19:00", "label": "晚餐"},
                     {"start": "12:00", "end": "13:30", "label": "午休"}])
    assert c.breaks == [Break(720, 810, "午休", "13:30"), Break(1080, 1140, "晚餐", "19:00")]


@pytest.mark.parametrize("bad", [
    {"breaks": [{"start": "25:00", "end": "13:30", "label": "x"}]},   # 非法小时
    {"breaks": [{"start": "12:00", "end": "12:00", "label": "x"}]},   # start >= end
    {"breaks": [{"start": "12:00", "end": "13:30", "label": "x"},
                {"start": "12:30", "end": "13:00", "label": "y"}]},   # 重叠
    {"breaks": [{"start": "12:00", "end": "13:30"}]},                 # 缺 label
    {"render_interval_min": 0},
    {"render_interval_min": 60},
    {"types": {"workday": {"start": 21, "end": 9}}},                  # start >= end
    {"types": {"workday": {"start": 9}}},                             # 只有 start
    {"overrides": {"2026-13-01": {"type": "rest"}}},                  # 非法日期
    {"overrides": {"2026-10-01": {"type": "nope"}}},                  # type 不存在
    {"overrides": {"2026-10-01": "rest"}},                            # 非对象
    {"overrides": "x"},                                               # 非对象
    {"weekends": [7]},                                                # 越界
])
def test_validation_rejects(bad):
    with pytest.raises(ValueError):
        Calendar(bad)


def test_load_from_file(tmp_path):
    p = tmp_path / "cal.json"
    p.write_text(json.dumps({"overrides": {"2026-10-01": {"type": "rest", "name": "国庆节"}}}),
                 encoding="utf-8")
    c = Calendar.load(str(p))
    assert c.day_type(date(2026, 10, 1)).name == "国庆节"
