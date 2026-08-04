from todos.db import Todo, init_db, list_todos, add_todo, update_todo, delete_todo


def test_crud(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    assert list_todos(db) == []

    t = add_todo(db, "回复邮件", prio="high")
    assert isinstance(t, Todo) and t.title == "回复邮件" and t.done is False
    add_todo(db, "买猫粮", prio="low")

    # not-done only, sorted by prio (high before low)
    todos = list_todos(db)
    assert [x.title for x in todos] == ["回复邮件", "买猫粮"]

    # mark done -> not shown by default
    update_todo(db, t.id, done=True)
    assert [x.title for x in list_todos(db)] == ["买猫粮"]
    assert len(list_todos(db, include_done=True)) == 2

    delete_todo(db, t.id)
    assert len(list_todos(db, include_done=True)) == 1
