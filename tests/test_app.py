from fastapi.testclient import TestClient
import app


def test_dashboard_png_served_with_cache_header(tmp_path, monkeypatch):
    # point output at a tmp file we control
    monkeypatch.setattr(app, "OUT", str(tmp_path / "dashboard.png"))
    (tmp_path / "dashboard.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    # don't start the scheduler for the test
    monkeypatch.setattr(app, "_start_scheduler", lambda: None)
    client = TestClient(app.app)
    r = client.get("/dashboard.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.headers["cache-control"] == "public, max-age=300"


def test_health(monkeypatch):
    monkeypatch.setattr(app, "_start_scheduler", lambda: None)  # avoid real render during lifespan
    client = TestClient(app.app)
    r = client.get("/healthz")
    assert r.status_code == 200


def test_todos_page_requires_auth(monkeypatch):
    monkeypatch.setattr(app, "_start_scheduler", lambda: None)   # also skips init_db (it's inside)
    client = TestClient(app.app)
    assert client.get("/todos").status_code == 401
    import base64
    from config import settings
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "secret")
    cred = base64.b64encode(b"admin:secret").decode()
    r = client.get("/todos", headers={"Authorization": f"Basic {cred}"})
    assert r.status_code == 200 and "<title>待办管理" in r.text
