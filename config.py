from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    sensecraft_device_id: str
    sensecraft_api_key: str
    qweather_host: str
    qweather_api_key: str
    qweather_location: str = "120.16,30.29"
    calendar_file: str              # 日历文件路径（必填）——时间/调度行为的唯一真相
    admin_username: str = "admin"   # Basic-auth username for /todos + /api/todos
    admin_password: str = "changeme"  # Basic-auth password — change before deploy
    tz: str = "Asia/Shanghai"
    todo_db: str = "todos.db"       # SQLite path for todos (volume-mount in Docker)
    log_level: str = "INFO"         # root log level (DEBUG/INFO/WARNING/...)


settings = Settings()
