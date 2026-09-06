"""Self-check for the agent todo board (rex.todos + todo_write tool). Run: python test_todos.py"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rex import todos
from rex.tools import todo_write


def check(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        sys.exit(1)


def main():
    # ── normalize_items ────────────────────────────────────────────────
    board = todos.normalize_items([
        {"content": "Analisis", "status": "pending"},
        {"content": "Tulis kode", "status": "in_progress"},
        {"content": "Uji", "status": "completed"},
    ])
    check("valid items kept", len(board) == 3)
    check("statuses preserved", [i["status"] for i in board] == ["pending", "in_progress", "completed"])

    check("non-list rejected", todos.normalize_items("bukan list") == [])
    check("non-dict entries dropped", todos.normalize_items(["x", 5, {"content": "ok", "status": "pending"}]) == [{"content": "ok", "status": "pending"}])
    check("bad status dropped", todos.normalize_items([{"content": "x", "status": "nanti"}]) == [])
    check("empty content dropped", todos.normalize_items([{"content": "  ", "status": "pending"}]) == [])
    check("cap 50 items", len(todos.normalize_items([{"content": f"t{i}", "status": "pending"} for i in range(200)])) == todos.MAX_ITEMS)

    # ── write / get / clear with a temp workspace ─────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        sid = "testsuite01"
        items = [
            {"content": "Langkah 1", "status": "completed"},
            {"content": "Langkah 2", "status": "in_progress"},
        ]
        check("write returns board", todos.write(sid, items, workspace=root) == todos.normalize_items(items))

        loaded = todos.get(sid)
        check("get returns stored items", len(loaded) == 2 and loaded[0]["content"] == "Langkah 1")

        anon = todos.write(None, [{"content": "anon", "status": "pending"}], workspace=root)
        check("anonymous write works", len(anon) == 1)

        weird = todos.write("../../evil", [{"content": "x", "status": "pending"}], workspace=root)
        check("weird session id sanitized", len(weird) == 1)
        check(
            "no traversal file created",
            not (root / "evil.json").exists() and (root / ".rex" / "todos").is_dir(),
        )

        todos.clear(sid)
        check("clear empties board", todos.get(sid) == [])

        todos.clear("nope")
        check("clear missing board is safe", True)

    # ── format_board / summary ─────────────────────────────────────────
    sample = [
        {"content": "A", "status": "completed"},
        {"content": "B", "status": "in_progress"},
        {"content": "C", "status": "pending"},
    ]
    text = todos.format_board(sample)
    check("format has [x] for completed", "[x] A" in text)
    check("format has [~] for in_progress", "[~] B" in text)
    check("format has [ ] for pending", "[ ] C" in text)
    check("empty board message", todos.format_board([]) == "(todo list kosong)")
    check("summary counts done", todos.summary(sample) == "1/3 selesai")
    check("summary empty", todos.summary([]) == "0/0")

    # ── session scope stack (nested runs) ─────────────────────────────
    todos.set_current_session("outer-session")
    check("current session pushed", todos.current_session() == "outer-session")
    todos.set_current_session(None)  # pop
    check("pop restores None", todos.current_session() is None)

    todos.set_current_session("outer")
    todos.set_current_session("nested")  # sub-agent run
    check("nested scope visible", todos.current_session() == "nested")
    todos.set_current_session(None)  # nested run ends
    check("outer scope restored after nested", todos.current_session() == "outer")
    todos.set_current_session(None)  # outer ends
    check("scope empty after all", todos.current_session() is None)

    # ── write listener (StepEvent plumbing) ───────────────────────────
    events = []
    todos.set_write_listener(lambda sid, board: events.append((sid, board)))
    try:
        todos.set_current_session("event-session")
        todos.write("event-session", [{"content": "X", "status": "pending"}])
        check("listener fired once", len(events) == 1)
        check("listener got session id", events[0][0] == "event-session")
        check("listener got board", events[0][1][0]["content"] == "X")
        todos.set_current_session(None)
    finally:
        todos.set_write_listener(None)
    todos.write("event-session", [])
    check("no listener -> no event", events and len(events) == 1)

    # ── todo_write tool surface ──────────────────────────────────────
    todos.set_current_session("tool-session")
    try:
        result = todo_write(todos=[{"content": "Cek tool", "status": "in_progress"}])
        check("tool reports update", "Todo list diperbarui" in result)
        check("tool board stored", todos.get("tool-session")[0]["content"] == "Cek tool")
        result = todo_write(todos=[{"content": "x", "status": "salah"}])
        check("tool reports ignored items", "tidak valid diabaikan" in result)
        result = todo_write(todos=[])
        check("tool empty clears board", "dikosongkan" in result)
    finally:
        todos.set_current_session(None)
        todos.clear("tool-session")

    # ── persisted shape is JSON with our fields ───────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        todos.write("persistence-check", [{"content": "P", "status": "completed"}], workspace=root)
        path = root / ".rex" / "todos" / "persistence-check.json"
        check("persisted file exists", path.is_file())
        data = json.loads(path.read_text(encoding="utf-8"))
        check("persisted shape valid", data == [{"content": "P", "status": "completed"}])


if __name__ == "__main__":
    main()

