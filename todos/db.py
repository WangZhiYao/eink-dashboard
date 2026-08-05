import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

PRIO_ORDER = {"high": 0, "normal": 1, "low": 2}


@dataclass
class Todo:
    id: int
    title: str
    done: bool
    prio: str
    created_at: str


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: str) -> None:
    with _connect(path) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS todos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                done INTEGER NOT NULL DEFAULT 0,
                prio TEXT NOT NULL DEFAULT 'normal',
                created_at TEXT NOT NULL
            )"""
        )


def list_todos(path: str, include_done: bool = False) -> list[Todo]:
    sql = "SELECT * FROM todos" if include_done else "SELECT * FROM todos WHERE done=0"
    with _connect(path) as conn:
        rows = conn.execute(sql).fetchall()
    todos = [Todo(r["id"], r["title"], bool(r["done"]), r["prio"], r["created_at"]) for r in rows]
    todos.sort(key=lambda t: (PRIO_ORDER.get(t.prio, 1), t.created_at))
    return todos


def add_todo(path: str, title: str, prio: str = "normal") -> Todo:
    now = datetime.now(timezone.utc).isoformat()
    with _connect(path) as conn:
        cur = conn.execute(
            "INSERT INTO todos (title, prio, created_at) VALUES (?, ?, ?)", (title, prio, now)
        )
        conn.commit()
        return Todo(cur.lastrowid, title, False, prio, now)


def update_todo(path: str, id: int, done: bool | None = None, title: str | None = None, prio: str | None = None) -> int:
    """Apply the given fields; return the number of rows actually changed (0 = no such id)."""
    with _connect(path) as conn:
        affected = 0
        if done is not None:
            affected += conn.execute("UPDATE todos SET done=? WHERE id=?", (1 if done else 0, id)).rowcount
        if title is not None:
            affected += conn.execute("UPDATE todos SET title=? WHERE id=?", (title, id)).rowcount
        if prio is not None:
            affected += conn.execute("UPDATE todos SET prio=? WHERE id=?", (prio, id)).rowcount
        conn.commit()
        return affected


def delete_todo(path: str, id: int) -> int:
    """Delete by id; return 1 if a row was removed, 0 if no such id."""
    with _connect(path) as conn:
        cur = conn.execute("DELETE FROM todos WHERE id=?", (id,))
        conn.commit()
        return cur.rowcount
