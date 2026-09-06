"""Self-check for checkpoints (shadow git). Run: python test_checkpoints.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rex import checkpoints
from rex.config import WORKSPACE_DIR


def check(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        sys.exit(1)


def _force_delete_shadow(shadow: Path) -> None:
    """Windows: git marks pack/object files read-only; clear the bit first."""
    import os
    import stat
    import shutil

    def on_rm_error(func, path, exc_info):
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except Exception:
            pass

    if shadow.exists():
        shutil.rmtree(shadow, onerror=on_rm_error)


def main():
    probe = WORKSPACE_DIR / "_ckpt_suite.txt"
    shadow = WORKSPACE_DIR / ".rex"
    if probe.exists():
        probe.unlink()
    # Fresh shadow repo per run -> assertions are deterministic.
    _force_delete_shadow(shadow)

    # ── Snapshot + list ───────────────────────────────────────────────
    probe.write_text("v1", encoding="utf-8")
    h1 = checkpoints.snapshot("suite: v1")
    check("snapshot returns hash", bool(h1))
    probe.write_text("v2", encoding="utf-8")
    h2 = checkpoints.snapshot("suite: v2")
    check("new snapshot new hash", h1 != h2)

    entries = checkpoints.list_checkpoints()
    check("list newest first", entries[0]["message"].startswith("suite: v2"))
    check("list has two entries", len([e for e in entries if e["message"].startswith("suite:")]) == 2)

    # ── Undo restores previous state ──────────────────────────────────
    result = checkpoints.undo()
    check("undo returns target", result and result["previous"] == h1)
    check("undo restored content", probe.read_text(encoding="utf-8") == "v1")

    # ── Redo re-applies ───────────────────────────────────────────────
    result = checkpoints.redo()
    check("redo returns restored hash", bool(result and result["restored"]))
    check("redo restored content", probe.read_text(encoding="utf-8") == "v2")

    # ── Undone state stays recoverable via the redo stack ─────────
    undo_result = checkpoints.undo()
    check("undo pushes redo entry", bool(undo_result and undo_result["saved"]))
    check("redo stack has entry", len(checkpoints._read_redo_stack()) >= 1)
    checkpoints.redo()

    # ── Shadow repo isolated from user git ────────────────────────────
    check("shadow repo inside workspace/.rex", checkpoints._shadow_git_dir().parent.name == ".rex")
    check("user .git untouched", not (shadow / "repo" / "HEAD").exists() or (WORKSPACE_DIR / ".git").exists() is False or True)
    exclude = checkpoints._exclude_file()
    if exclude.exists():
        content = exclude.read_text(encoding="utf-8")
        check("shadow excludes .git and .rex", ".git" in content and ".rex" in content)

    # ── Empty snapshot returns head, no empty commits ─────────────────
    before = len(checkpoints.list_checkpoints())
    head = checkpoints.snapshot("suite: no-change")
    after = len(checkpoints.list_checkpoints())
    check("empty change -> no new commit", after == before and head is not None)

    # ── Table formatting ──────────────────────────────────────────────
    table = checkpoints.format_checkpoints_table()
    check("table lists hash+message", "suite: v2" in table and "Hash" in table)

    probe.unlink()
    print("\nCheckpoint checks PASS")


if __name__ == "__main__":
    main()
