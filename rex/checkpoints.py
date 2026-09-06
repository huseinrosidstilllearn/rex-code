"""
rex.checkpoints
===============
Checkpoints & undo for BUILD actions — a *shadow* git repository.

- Lives in ``<workspace>/.rex/repo`` with its own GIT_DIR, so the user's
  own ``.git`` is never touched (and non-git folders still get checkpoints).
- The agent snapshots automatically before every destructive BUILD action
  (write_file / edit_file / delete_file / run_command / git_publish).
- ``/checkpoints`` lists history, ``/undo`` rolls the workspace back one
  step, ``/redo`` re-applies. Undo itself is checkpointed, so nothing is
  ever lost.

Failures never block the action that triggered them — checkpoints are a
bonus, not a gate.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

SHADOW_DIRNAME = ".rex"
GIT_DIRNAME = "repo"
MAX_LIST = 50
MAX_REDO_STACK = 100
COMMAND_TIMEOUT = 30

# Never committed into the shadow repo (user VCS state, caches, ourselves).
EXCLUDE_ENTRIES = (
    ".git", ".rex", "__pycache__", "node_modules", ".venv", "venv",
    "dist", "build", ".pytest_cache", ".mypy_cache", ".ruff_cache",
)


def _workspace() -> Path:
    from rex.config import WORKSPACE_DIR
    return Path(WORKSPACE_DIR)


def _shadow_git_dir() -> Path:
    return _workspace() / SHADOW_DIRNAME / GIT_DIRNAME


def _git_env() -> dict:
    import os
    env = os.environ.copy()
    env["GIT_DIR"] = str(_shadow_git_dir())
    env["GIT_WORK_TREE"] = str(_workspace())
    env["GIT_AUTHOR_NAME"] = env.get("GIT_AUTHOR_NAME", "Rex Checkpoint")
    env["GIT_COMMITTER_NAME"] = env.get("GIT_COMMITTER_NAME", "Rex Checkpoint")
    env["GIT_AUTHOR_EMAIL"] = env.get("GIT_AUTHOR_EMAIL", "checkpoint@rex.local")
    env["GIT_COMMITTER_EMAIL"] = env.get("GIT_COMMITTER_EMAIL", "checkpoint@rex.local")
    return env


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git", *args], env=_git_env(), cwd=str(_workspace()),
        capture_output=True, text=True, timeout=COMMAND_TIMEOUT, encoding="utf-8", errors="replace",
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])} failed: {result.stderr.strip()[:200]}")
    return result


def _initialized() -> bool:
    return (_shadow_git_dir() / "HEAD").exists()


def _ensure_repo() -> None:
    if _initialized():
        return
    git_dir = _shadow_git_dir()
    git_dir.mkdir(parents=True, exist_ok=True)
    _run("init", "--quiet", check=False)
    _run("config", "core.autocrlf", "false")
    _write_exclude_file()


def _exclude_file() -> Path:
    return _shadow_git_dir() / "info" / "exclude"


def _redo_stack_file() -> Path:
    return _workspace() / SHADOW_DIRNAME / "redo_stack"


def _read_redo_stack() -> List[str]:
    try:
        return [line.strip() for line in _redo_stack_file().read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        return []


def _write_redo_stack(hashes: List[str]) -> None:
    try:
        _redo_stack_file().parent.mkdir(parents=True, exist_ok=True)
        _redo_stack_file().write_text("\n".join(hashes) + "\n", encoding="utf-8")
    except OSError:
        pass


def _push_redo(commit_hash: str) -> None:
    stack = _read_redo_stack()
    stack.append(commit_hash)
    _write_redo_stack(stack[-MAX_REDO_STACK:])


def _pop_redo() -> Optional[str]:
    stack = _read_redo_stack()
    if not stack:
        return None
    commit_hash = stack.pop()
    _write_redo_stack(stack)
    return commit_hash


def _clear_redo() -> None:
    try:
        _redo_stack_file().unlink(missing_ok=True)
    except OSError:
        pass


def _write_exclude_file() -> None:
    """Shadow-repo-local excludes; also hides them from `git status` noise."""
    exclude = _exclude_file()
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text("\n".join(EXCLUDE_ENTRIES) + "\n", encoding="utf-8")


def snapshot(label: str) -> Optional[str]:
    """
    Commit the current workspace state into the shadow repo.
    Returns the commit hash, or None when there is nothing to record /
    something failed. Never raises.
    """
    try:
        _ensure_repo()
        _run("add", "-A")
        # Skip empty snapshots (e.g. nothing changed since the last one).
        status = _run("status", "--porcelain", check=False)
        if not status.stdout.strip():
            head = head_hash()
            return head  # state already recorded; caller just wants a hash
        message = label.replace('"', "'")
        _run("commit", "-m", message, "--quiet")
        # A real (user-visible) change invalidates the redo stack — classic
        # undo/redo semantics: a new action clears the redo history.
        _clear_redo()
        return head_hash()
    except Exception:
        return None


def head_hash() -> Optional[str]:
    try:
        result = _run("rev-parse", "HEAD", check=False)
        return result.stdout.strip() or None
    except Exception:
        return None


def list_checkpoints(limit: int = MAX_LIST) -> List[dict]:
    """Newest-first checkpoint list: {hash, message, time}."""
    if not _initialized():
        return []
    try:
        result = _run(
            "log", f"-n{max(1, limit)}", "--date=iso",
            "--pretty=format:%h%x09%ad%x09%s", check=False,
        )
    except Exception:
        return []
    entries = []
    for line in result.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            entries.append({"hash": parts[0], "time": parts[1], "message": parts[2]})
    return entries


def undo() -> Optional[dict]:
    """
    Roll the workspace back one step via ``git reset --hard``.

    Semantics: undo removes the most recent change — the uncommitted
    worktree changes when dirty, otherwise the newest commit.

    The abandoned state stays recoverable: its hash is pushed onto the
    redo stack (a file under .rex/, independent of git history). Dirty
    worktrees are committed first (UNDO label) so nothing is ever lost.
    Returns {"previous", "saved"} or None.
    """
    if not _initialized():
        return None
    try:
        log = _run("log", "--pretty=format:%H", "-n2", check=False).stdout.splitlines()
        if len(log) < 2:
            return None  # nothing to undo into
        old_tip = head_hash()
        dirty = bool(_run("status", "--porcelain", check=False).stdout.strip())
        if dirty:
            saved = snapshot("UNDO — auto-saved before rollback")
            target = old_tip      # keep last commit; drop uncommitted changes
            pushed = saved or old_tip
        else:
            saved = None
            target = log[1]       # roll back to the previous checkpoint
            pushed = old_tip
        _run("reset", "--hard", target)
        _push_redo(pushed)
        return {"previous": target, "saved": pushed}
    except Exception:
        return None


def redo() -> Optional[dict]:
    """
    Re-apply the last undone state (pop the redo stack, reset to it).
    Returns {"restored": hash} or None when the stack is empty.
    """
    if not _initialized():
        return None
    try:
        commit_hash = _pop_redo()
        if not commit_hash:
            return None
        _run("reset", "--hard", commit_hash)
        return {"restored": commit_hash}
    except Exception:
        return None


def label_for_action(action: str, summary: str) -> str:
    return f"{action}: {summary}"[:120]


# ── Slash-command surfaces ────────────────────────────────────────────

def format_checkpoints_table() -> str:
    entries = list_checkpoints()
    if not entries:
        return "(belum ada checkpoint)"
    lines = ["Hash      Waktu                Keterangan", "-" * 70]
    for entry in entries:
        lines.append(f"{entry['hash']:<9} {entry['time'][:19]}  {entry['message']}")
    return "\n".join(lines)


def ensure_gitignore_entry() -> None:
    """Keep the shadow repo out of the user's own git status."""
    try:
        gitignore = _workspace() / ".gitignore"
        existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
        if ".rex/" not in existing:
            with open(gitignore, "a", encoding="utf-8") as handle:
                if existing and not existing.endswith("\n"):
                    handle.write("\n")
                handle.write(".rex/\n")
    except Exception:
        pass
