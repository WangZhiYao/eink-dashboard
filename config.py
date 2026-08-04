from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    sensecraft_device_id: str
    sensecraft_api_key: str
    qweather_host: str
    qweather_api_key: str
    qweather_location: str = "120.16,30.29"
    render_interval_min: int = Field(5, ge=1, le=59)      # daytime refresh rate (minutes); SenseCraft widget should match
    weather_cache_min: int = 30       # cache QWeather responses for this many minutes
    pomodoro_start: int = Field(9, ge=1, le=23)           # Pomodoro + fast-refresh window start hour
    pomodoro_end: int = Field(21, ge=2, le=23)            # Pomodoro + fast-refresh window end hour (exclusive)
    lunch_start: str = "12:00"        # lunch break start (HH:MM) — Pomodoro pauses
    lunch_end: str = "13:30"          # lunch break end (HH:MM)
    admin_username: str = "admin"      # Basic-auth username for /todos + /api/todos
    admin_password: str = "changeme"   # Basic-auth password — change before deploy
    tz: str = "Asia/Shanghai"
    todo_db: str = "todos.db"           # SQLite path for todos (volume-mount in Docker)
    log_level: str = "INFO"             # root log level (DEBUG/INFO/WARNING/...); tunable via LOG_LEVEL env

    @model_validator(mode="after")
    def _pomodoro_window_is_valid(self) -> "Settings":
        # Guards the cron expressions built in app._start_scheduler(): an empty or
        # inverted window would produce an invalid cron field and crash scheduler start.
        if self.pomodoro_end <= self.pomodoro_start:
            raise ValueError("pomodoro_end must be greater than pomodoro_start")
        return self


settings = Settings()
