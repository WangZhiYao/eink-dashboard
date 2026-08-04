import logging
import logging.config
import os
import sys
from contextlib import asynccontextmanager
from zoneinfo import ZoneInfo
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from apscheduler.schedulers.background import BackgroundScheduler
from config import settings
from render import render_now
from todos import db as todos_db
from todos.api import router as todos_router
from todos.auth import verify_admin

log = logging.getLogger("app")

# Configure logging once at import. render.py / fetchers already call
# log.info/log.warning/log.exception for the things that matter (render
# success+failure, weather/SHT40 degradation), but with no handler configured
# those records are silently dropped — so "the dashboard stopped rendering"
# was invisible. This attaches a stdout handler at root level so they reach
# `docker compose logs`. uvicorn's own LOGGING_CONFIG only touches the
# uvicorn.* loggers (disable_existing_loggers=False), so this root handler
# survives regardless of whether uvicorn configures logging before or after.
logging.config.dictConfig({
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {"format": "%(asctime)s %(levelname)-8s %(name)s | %(message)s"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "stream": sys.stdout,
        },
    },
    "root": {"handlers": ["console"], "level": settings.log_level.upper()},
})

templates = Jinja2Templates(directory="templates")

OUT = "static/dashboard.png"
_scheduler = None


def _start_scheduler():
    global _scheduler
    log.info(
        "eink-dashboard starting | tz=%s render_interval=%dm pomodoro=%d-%d lunch=%s-%s todo_db=%s log_level=%s",
        settings.tz, settings.render_interval_min, settings.pomodoro_start,
        settings.pomodoro_end, settings.lunch_start, settings.lunch_end,
        settings.todo_db, settings.log_level,
    )
    todos_db.init_db(settings.todo_db)
    _scheduler = BackgroundScheduler(timezone=ZoneInfo(settings.tz))
    # Render only during the work window [pomodoro_start, pomodoro_end), every
    # render_interval_min. Overnight we stop rendering entirely — the screen
    # holds its last image (no e-ink flashes, no Chromium CPU) until the
    # pre-render below kicks the next work day off.
    day_hours = f"{settings.pomodoro_start}-{settings.pomodoro_end - 1}"
    _scheduler.add_job(render_now, "cron", hour=day_hours, minute=f"*/{settings.render_interval_min}", id="render_day")
    # pre-render just before the day starts (e.g. 8:55) so the 9:00 pull gets a fresh image
    _scheduler.add_job(render_now, "cron", hour=settings.pomodoro_start - 1, minute=60 - settings.render_interval_min, id="render_prerender")
    _scheduler.start()
    # render once immediately so the first serve isn't empty
    try:
        render_now()
    except Exception:
        pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _start_scheduler()
    yield
    if _scheduler:
        _scheduler.shutdown(wait=False)


app = FastAPI(lifespan=lifespan)

app.include_router(todos_router)


@app.get("/todos", response_class=HTMLResponse, dependencies=[Depends(verify_admin)])
def todos_page(request: Request):
    return templates.TemplateResponse(request, "todos.html")


@app.get("/healthz")
def health():
    return {"ok": True}


@app.get("/dashboard.png")
def dashboard():
    if not os.path.exists(OUT):
        raise HTTPException(status_code=503, detail="not ready")
    return FileResponse(
        OUT,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"},
    )
