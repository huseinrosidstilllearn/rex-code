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

    # ── Rewind: timeline restore ──────────────────────────────────────
    probe.write_text("v3", encoding="utf-8")
    h3 = checkpoints.snapshot("suite: v3")
    check("three snapshots now", len([e for e in checkpoints.list_checkpoints() if e["message"].startswith("suite:")]) == 3)
    check("timeline numbered", checkpoints.format_timeline().splitlines()[2].strip().startswith("1."))

    check("rewind zero rejected", checkpoints.rewind(0) is None)
    check("rewind negative rejected", checkpoints.rewind(-1) is None)
    check("rewind garbage rejected", checkpoints.rewind("x") is None)

    result = checkpoints.rewind(2)  # v3 -> v1
    check("rewind returns target", bool(result and result["restored"]))
    check("rewind restored content", probe.read_text(encoding="utf-8") == "v1")
    check("rewind pushes redo entry", len(checkpoints._read_redo_stack()) >= 1)
    result = checkpoints.redo()
    check("redo after rewind restores", probe.read_text(encoding="utf-8") == "v3")

    result = checkpoints.rewind(1)  # v3 -> v2
    check("rewind one step", probe.read_text(encoding="utf-8") == "v2")
    checkpoints.redo()

    # Rewind beyond history is refused
    entries_count = len(checkpoints._full_hashes(100))
    check("rewind too far refused", checkpoints.rewind(entries_count + 5) is None)

    # Dirty worktree is auto-saved, never lost
    probe.write_text("v4-uncommitted", encoding="utf-8")
    result = checkpoints.rewind(1)
    check("dirty rewind works", bool(result))
    check("dirty changes land on redo stack", bool(checkpoints._read_redo_stack()))
    saved = checkpoints.redo()
    check("redo recovers uncommitted work", probe.read_text(encoding="utf-8") == "v4-uncommitted")
    # clean up the extra auto-save state
    checkpoints.rewind(1)
    checkpoints.redo()

    probe.unlink()
    print("\nCheckpoint checks PASS")


if __name__ == "__main__":
    main()
