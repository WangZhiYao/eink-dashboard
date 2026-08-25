"""HTML → PNG 截图管线：Playwright 截图 + asyncio 规避 + 原子替换。"""
import asyncio
import os
import threading

from playwright.sync_api import sync_playwright

from render.svg import render_html

OUT_PATH = "static/dashboard.png"


def _screenshot(html_str: str, out_path: str) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 800, "height": 480})
        page.set_content(html_str, wait_until="load")
        page.screenshot(path=out_path, clip={"x": 0, "y": 0, "width": 800, "height": 480})
        browser.close()


def _html_to_png(html_str: str, out_path: str) -> None:
    root, ext = os.path.splitext(out_path)
    tmp = f"{root}.tmp{ext}"          # keep .png suffix — Playwright infers format from extension
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)   # Fix #5: ensure dir exists
    # Playwright's sync API refuses to run inside a running asyncio loop
    # (e.g. FastAPI's lifespan). When one is running, dispatch the sync
    # screenshot to a worker thread — no loop is running there. We never use
    # asyncio.run here, so this is safe to call from the lifespan.
    try:
        asyncio.get_running_loop()
        in_loop = True
    except RuntimeError:
        in_loop = False
    if in_loop:
        # sync Playwright can't run inside a running asyncio loop; run it on a
        # worker thread, but surface any error back to the caller instead of
        # letting the thread boundary swallow it.
        holder: dict = {}

        def _run():
            try:
                _screenshot(html_str, tmp)
            except BaseException as e:  # re-raised in the caller thread
                holder["error"] = e

        t = threading.Thread(target=_run)
        t.start()
        t.join()
        if "error" in holder:
            raise holder["error"]
    else:
        _screenshot(html_str, tmp)
    os.replace(tmp, out_path)


def render_to_png(context: dict, out_path: str = OUT_PATH) -> None:
    _html_to_png(render_html(context), out_path)
