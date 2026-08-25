"""本地预览渲染：验证逐时表头「降水概率」一行展示。

用法: .venv\Scripts\python.exe render_preview.py
输出: static/preview.png（800×480，与设备一致）
"""
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))
from fetchers import sht40, weather
from fetchers.gold import GoldData
from render import render_to_png

CTX = {
    "time_str": "10:07",
    "date_str": "2026.08.08",
    "weekday": "星期六",
    "indoor": sht40.Sht40Data(temp=26.0, humidity=42.0, battery=87),
    "weather": weather.WeatherData(
        current={"temp": 28, "text": "多云", "icon": "104"}, hi=29, lo=21, aqi=45,
        hourly=[
            {"label": "现在", "text": "多云", "temp": 28, "rain": 34},
            {"label": "11:00", "text": "晴", "temp": 30, "rain": 10},
            {"label": "12:00", "text": "多云", "temp": 29, "rain": 20},
            {"label": "13:00", "text": "阵雨", "temp": 26, "rain": 60},
        ],
        sunrise="05:42", sunset="19:08"),
    "lunar": "六月廿六",
    "pomodoro": {"active": True, "phase": "work", "remaining": 18},
    "todos": [
        {"title": "回复邮件", "prio": "high"},
        {"title": "整理周报", "prio": "normal"},
        {"title": "下午开会", "prio": "low"},
    ],
    "day_type": "workday",
    "day_name": "",
    "gold": GoldData(
        current=760.50,
        open=755.00,
        high=762.80,
        low=753.20,
        points=[
            {"time": "09:00:00", "price": 755.00},
            {"time": "09:30:00", "price": 756.50},
            {"time": "10:00:00", "price": 758.20},
            {"time": "10:30:00", "price": 757.10},
            {"time": "11:00:00", "price": 759.30},
            {"time": "11:30:00", "price": 761.00},
            {"time": "13:00:00", "price": 760.50},
            {"time": "13:30:00", "price": 762.80},
            {"time": "14:00:00", "price": 761.50},
            {"time": "14:30:00", "price": 760.50},
        ],
    ),
}

render_to_png(CTX, "static/preview.png")
print("preview written to static/preview.png")
