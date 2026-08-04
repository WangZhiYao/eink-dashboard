import base64
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient
import todos.auth as auth
from config import settings

from todos import db as todos_db
from todos.api import router


def _app():
    app = FastAPI()

    @app.get("/prot", dependencies=[Depends(auth.verify_admin)])
    def prot():
        return {"ok": True}
    return app


def _basic(user, pw):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()}


def _client(monkeypatch):
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "secret")
    return TestClient(_app())


def test_no_creds_401(monkeypatch):
    r = _client(monkeypatch).get("/prot")
    assert r.status_code == 401
    assert "Basic" in r.headers.get("www-authenticate", "")


def test_basic_auth_ok(monkeypatch):
    r = _client(monkeypatch).get("/prot", headers=_basic("admin", "secret"))
    assert r.status_code == 200


def test_wrong_password_401(monkeypatch):
    r = _client(monkeypatch).get("/prot", headers=_basic("admin", "wrong"))
    assert r.status_code == 401


def test_wrong_username_401(monkeypatch):
    r = _client(monkeypatch).get("/prot", headers=_basic("other", "secret"))
    assert r.status_code == 401


def _router_client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "secret")
    monkeypatch.setattr(settings, "todo_db", str(tmp_path / "t.db"))
    todos_db.init_db(settings.todo_db)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), _basic("admin", "secret")


def test_api_crud(monkeypatch, tmp_path):
    client, h = _router_client(monkeypatch, tmp_path)

    r = client.post("/api/todos", json={"title": "写周报", "prio": "high"}, headers=h)
    assert r.status_code == 201 and r.json()["title"] == "写周报"
    tid = r.json()["id"]
    client.post("/api/todos", json={"title": "买猫粮"}, headers=h)

    r = client.get("/api/todos", headers=h)
    assert [t["title"] for t in r.json()] == ["写周报", "买猫粮"]

    assert client.patch(f"/api/todos/{tid}", json={"done": True}, headers=h).status_code == 200
    r = client.get("/api/todos", headers=h)
    assert [t["title"] for t in r.json()] == ["买猫粮"]

    assert client.delete(f"/api/todos/{tid}", headers=h).status_code == 204
    assert len(client.get("/api/todos?include_done=true", headers=h).json()) == 1


def test_api_requires_auth(monkeypatch, tmp_path):
    client, _ = _router_client(monkeypatch, tmp_path)
    assert client.get("/api/todos").status_code == 401


def test_api_rejects_invalid_prio(monkeypatch, tmp_path):
    client, h = _router_client(monkeypatch, tmp_path)
    r = client.post("/api/todos", json={"title": "x", "prio": "evil"}, headers=h)
    assert r.status_code == 422                      # server-side whitelist rejects it
    assert client.post("/api/todos", json={"title": "y", "prio": "high"}, headers=h).status_code == 201


def test_api_patch_and_delete_missing_todo_404(monkeypatch, tmp_path):
    client, h = _router_client(monkeypatch, tmp_path)
    assert client.patch("/api/todos/9999", json={"done": True}, headers=h).status_code == 404
    assert client.delete("/api/todos/9999", headers=h).status_code == 404
