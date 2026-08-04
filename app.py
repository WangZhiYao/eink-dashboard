import os
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

templates = Jinja2Templates(directory="templates")

OUT = "static/dashboard.png"
_scheduler = None


def _start_scheduler():
    global _scheduler
    todos_db.init_db(settings.todo_db)
    _scheduler = BackgroundScheduler(timezone=ZoneInfo(settings.tz))
    # Fast refresh (every render_interval_min) during the Pomodoro window;
    # slower (every 30 min) overnight to spare e-ink flashes / battery.
    day_hours = f"{settings.pomodoro_start}-{settings.pomodoro_end - 1}"
    night_hours = f"0-{settings.pomodoro_start - 1},{settings.pomodoro_end}-23"
    _scheduler.add_job(render_now, "cron", hour=day_hours, minute=f"*/{settings.render_interval_min}", id="render_day")
    _scheduler.add_job(render_now, "cron", hour=night_hours, minute="*/30", id="render_night")
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
