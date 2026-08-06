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


def _render_schedule(s):
    """Cron (job_id, hour, minute) for each render job, derived from settings.

    Pure function so the daily schedule is unit-testable without booting a live
    scheduler / DB / Chromium. Consumed by _start_scheduler() below.
    """
    return [
        # every render_interval_min during the work window [start, end)
        ("render_day", f"{s.pomodoro_start}-{s.pomodoro_end - 1}", f"*/{s.render_interval_min}"),
        # one final render at the top of pomodoro_end (e.g. 21:00), then the screen
        # holds its last image overnight — no e-ink flashes / Chromium CPU until the
        # next day's pre-render. Without this the last render was 20:55 (render_day's
        # hour field "9-20" is inclusive, so hour 21 never fired).
        ("render_final", str(s.pomodoro_end), "0"),
        # pre-render just before the day starts (e.g. 8:55) so the 9:00 pull gets a fresh image
        ("render_prerender", str(s.pomodoro_start - 1), str(60 - s.render_interval_min)),
    ]


def _start_scheduler():
    global _scheduler
    log.info(
        "eink-dashboard starting | tz=%s render_interval=%dm pomodoro=%d-%d breaks=%s todo_db=%s log_level=%s",
        settings.tz, settings.render_interval_min, settings.pomodoro_start,
        settings.pomodoro_end, settings.breaks,
        settings.todo_db, settings.log_level,
    )
    todos_db.init_db(settings.todo_db)
    _scheduler = BackgroundScheduler(timezone=ZoneInfo(settings.tz))
    for job_id, hour, minute in _render_schedule(settings):
        _scheduler.add_job(render_now, "cron", hour=hour, minute=minute, id=job_id)
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
