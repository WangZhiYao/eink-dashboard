from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from config import settings
from todos import db
from todos.auth import verify_admin

router = APIRouter(prefix="/api/todos", dependencies=[Depends(verify_admin)])


class TodoIn(BaseModel):
    title: str
    prio: Literal["high", "normal", "low"] = "normal"


class TodoPatch(BaseModel):
    title: str | None = None
    done: bool | None = None


@router.get("")
def list_all(include_done: bool = Query(default=False)):
    return [t.__dict__ for t in db.list_todos(settings.todo_db, include_done=include_done)]


@router.post("", status_code=201)
def create(todo: TodoIn):
    return db.add_todo(settings.todo_db, todo.title, todo.prio).__dict__


@router.patch("/{todo_id}")
def update(todo_id: int, patch: TodoPatch):
    had_fields = patch.done is not None or patch.title is not None
    affected = db.update_todo(settings.todo_db, todo_id, done=patch.done, title=patch.title)
    if had_fields and affected == 0:
        raise HTTPException(status_code=404, detail="not found")
    return {"ok": True}


@router.delete("/{todo_id}", status_code=204)
def remove(todo_id: int):
    if db.delete_todo(settings.todo_db, todo_id) == 0:
        raise HTTPException(status_code=404, detail="not found")
    return None
