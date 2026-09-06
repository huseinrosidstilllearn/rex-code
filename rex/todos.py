"""
rex.todos
=========
Agent todo list — a small shared task board per session.

- The agent updates it via the ``todo_write`` tool (structured: a list of
  ``{content, status}`` items, status in pending/in_progress/completed).
- State is kept in memory for the active session and persisted under
  ``<workspace>/.rex/todos/<session_id>.json`` so it survives restarts and
  can be listed by other surfaces (CLI ``/todos``, scheduler reports).
- The TUI renders the current list on every ``todo_update`` StepEvent.
- Never a gate: todo failures are logged and ignored — the agent loop must
  not stop because a task board could not be written.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Dict, List, Optional

from rex.config import WORKSPACE_DIR

TODOS_DIRNAME = ".rex/todos"
VALID_STATUSES = ("pending", "in_progress", "completed")
MAX_ITEMS = 50
MAX_CONTENT_CHARS = 200

_lock = threading.RLock()
# Active board per session id: {session_id: [ {content, status}, ... ]}
_boards: Dict[str, List[dict]] = {}

# Optional write-notify hook (session_id, board) — installed by rex.core so
# every provider loop (Gemini native + router) gets todo_update events
# without the tools layer needing an on_step reference.
_notify: Optional[object] = None


def set_write_listener(listener) -> None:
    """Register ``listener(session_id, board)`` called after each write."""
    global _notify
    _notify = listener


def _fire_write(session_id: Optional[str], board: List[dict]) -> None:
    if _notify is None:
        return
    try:
        _notify(session_id, board)
    except Exception:
        pass  # UI notifications must never break the tool

# Session id of the RexAgent currently running in this process (set by
# rex.core at the start of every run). The todo_write tool reads it so the
# board lands on the right session even in headless/CLI mode. It is a
# *stack*: nested runs (sub-agents) save & restore the outer scope.
_current: List[Optional[str]] = []


def current_session() -> Optional[str]:
    """Session id of the innermost running agent round (None outside a run)."""
    return _current[-1] if _current else None


def set_current_session(session_id: Optional[str]) -> None:
    """
    Scope todo_write to this session for the duration of a RexAgent.run.

    Push on entry; pass ``None`` to pop (restores the outer scope when a
    sub-agent's nested run finishes first).
    """
    if isinstance(session_id, str) and session_id.strip():
        _current.append(session_id.strip())
    elif _current:
        _current.pop()  # end of run: restore the enclosing scope
    # else: nothing to pop — a run() with no session id leaves scope untouched


def todos_dir(workspace: Optional[Path] = None) -> Path:
    """Directory holding persisted todo boards: ``<workspace>/.rex/todos``."""
    root = Path(workspace) if workspace else Path(WORKSPACE_DIR)
    return root / TODOS_DIRNAME


def _board_path(session_id: str, workspace: Optional[Path] = None) -> Optional[Path]:
    if not isinstance(session_id, str) or not session_id.strip():
        return None
    # Keep the filename filesystem-safe (session ids are hex, but be strict).
    safe = "".join(ch for ch in session_id.strip() if ch.isalnum() or ch in "-_")
    if not safe:
        return None
    return todos_dir(workspace) / f"{safe[:64]}.json"


def normalize_items(raw) -> List[dict]:
    """
    Validate + cap a raw todo list from the LLM into a clean board.

    Anything malformed is dropped (never an error): the tool returns an
    explicit message instead so the model can self-correct.
    """
    if not isinstance(raw, list):
        return []
    items: List[dict] = []
    for entry in raw[:MAX_ITEMS]:
        if not isinstance(entry, dict):
            continue
        content = str(entry.get("content", "")).strip()[:MAX_CONTENT_CHARS]
        status = str(entry.get("status", "pending")).strip().lower()
        if not content or status not in VALID_STATUSES:
            continue
        items.append({"content": content, "status": status})
    return items


def write(session_id: Optional[str], items, workspace: Optional[Path] = None) -> List[dict]:
    """
    Replace the board for ``session_id`` (normalized) and persist it.

    Returns the stored board. A missing/invalid session id or a failing
    disk write still updates the in-memory board (best effort) — todos are
    a UI aid, not a data pipeline.
    """
    board = normalize_items(items)
    key = session_id or "_anonymous"
    with _lock:
        _boards[key] = board
    path = _board_path(key, workspace)
    if path is not None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(board, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass  # persist is best effort
    _fire_write(key if session_id else None, board)
    return board


def get(session_id: Optional[str], workspace: Optional[Path] = None) -> List[dict]:
    """Current board for a session (memory first, then disk)."""
    key = session_id or "_anonymous"
    with _lock:
        board = _boards.get(key)
    if board is not None:
        return list(board)
    path = _board_path(key, workspace)
    if path is not None and path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if isinstance(data, list):
            return normalize_items(data)
    return []


def clear(session_id: Optional[str], workspace: Optional[Path] = None) -> None:
    """Drop the in-memory board and delete the persisted file."""
    key = session_id or "_anonymous"
    with _lock:
        _boards.pop(key, None)
    path = _board_path(key, workspace)
    if path is not None:
        try:
            path.unlink()
        except OSError:
            pass


def format_board(items: List[dict]) -> str:
    """Render a board for chat/CLI: one line per item with a status marker."""
    if not items:
        return "(todo list kosong)"
    markers = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}
    lines = []
    for item in items:
        marker = markers.get(item["status"], "[ ]")
        lines.append(f"{marker} {item['content']}")
    return "\n".join(lines)


def summary(items: List[dict]) -> str:
    """One-line progress summary, e.g. ``2/5 selesai``."""
    if not items:
        return "0/0"
    done = sum(1 for item in items if item["status"] == "completed")
    return f"{done}/{len(items)} selesai"
