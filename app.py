import logging
import logging.config
import os
import sys
import time
from contextlib import asynccontextmanager
from zoneinfo import ZoneInfo
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from apscheduler.schedulers.background import BackgroundScheduler
from config import settings
from daytypes import calendar
from render import render_now, render_tick
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
        "eink-dashboard starting | tz=%s calendar=%s interval=%dm breaks=%s todo_db=%s log_level=%s",
        settings.tz, settings.calendar_file, calendar.render_interval_min,
        [(b.label, b.end_hm) for b in calendar.breaks],
        settings.todo_db, settings.log_level,
    )
    todos_db.init_db(settings.todo_db)
    _scheduler = BackgroundScheduler(timezone=ZoneInfo(settings.tz))
    _scheduler.add_job(render_tick, "cron", hour="*",
                       minute=f"*/{calendar.render_interval_min}", id="render_tick")
    _scheduler.start()
    # render once immediately so the first serve isn't empty; failure is logged
    # by render_now itself and the cron job will retry
    try:
        render_now()
    except Exception:
        log.warning("initial render failed; scheduler will retry")


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

    # Re-render on demand when the cached image is older than the staleness
    # threshold, so the device always gets a fresh image regardless of when
    # the last cron tick fired. The cron pre-renders every render_interval_min
    # as a safety net; this on-demand path keeps the display in sync.
    age = time.time() - os.path.getmtime(OUT)
    if age > calendar.stale_seconds:
        try:
            render_now()
        except Exception:
            log.warning("on-demand render failed; serving cached image")

    return FileResponse(
        OUT,
        media_type="image/png",
        headers={"Cache-Control": "no-cache"},
    )
