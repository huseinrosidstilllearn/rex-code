"""Self-check review module (session diff, doctor, test hook). Run: python test_review.py"""

import os
import stat
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rex import checkpoints
from rex.review import (
    doctor,
    format_doctor,
    format_session_diff,
    run_tests_hook,
    session_diff,
)
from rex.config import WORKSPACE_DIR


def check(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        sys.exit(1)


def _force_remove(func, path, _exc):
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


def reset_shadow():
    shadow = WORKSPACE_DIR / ".rex"
    if shadow.exists():
        import shutil
        shutil.rmtree(shadow, onerror=_force_remove)


def main():
    reset_shadow()
    probe = WORKSPACE_DIR / "review_probe.txt"
    try:
        # ── 1. Session diff: no shadow repo yet ───────────────────────────
        check("no shadow repo -> None", session_diff() is None)
        check("format explains missing checkpoints", "belum ada checkpoint" in format_session_diff())

        # ── 2. Session diff: change after checkpoint shows up ─────────────
        probe.write_text("v1\n", encoding="utf-8")
        assert checkpoints.snapshot("test: baseline"), "snapshot should record baseline"
        probe.write_text("v2 — changed\n", encoding="utf-8")
        diff = session_diff()
        check("diff detects session change", diff is not None and "review_probe.txt" in diff)
        check("diff shows modification", diff and "v2" in diff)

        # Clean state -> empty diff
        assert checkpoints.snapshot("test: after change")
        check("clean state -> empty diff", session_diff() == "")
        check("format shows clean message", "tidak ada perubahan" in format_session_diff())
    finally:
        probe.unlink(missing_ok=True)
        try:
            checkpoints.snapshot("test: cleanup")
        except Exception:
            pass

    # ── 3. Test hook ────────────────────────────────────────────────────
    result = run_tests_hook(cfg={})
    check("hook disabled -> not ran", result["ran"] is False)

    result = run_tests_hook(cfg={"test_hook": {"enabled": True, "command": ""}})
    check("hook without command -> not ran", result["ran"] is False)

    result = run_tests_hook(cfg={"test_hook": {"enabled": True, "command": "python -c \"print('hook-ok')\"", "timeout_sec": 30}})
    check("hook runs and passes", result["ran"] is True and result["passed"] is True)
    check("hook captures output", "hook-ok" in result["output"])

    result = run_tests_hook(cfg={"test_hook": {"enabled": True, "command": "python -c \"import sys; sys.exit(3)\"", "timeout_sec": 30}})
    check("hook reports failure", result["ran"] is True and result["passed"] is False)

    result = run_tests_hook(cfg={"test_hook": {"enabled": True, "command": "python -c \"import time; time.sleep(30)\"", "timeout_sec": 5}})
    check("hook timeout -> failure", result["passed"] is False and "timeout" in result["output"])

    # ── 4. Doctor ──────────────────────────────────────────────────────
    report = doctor()
    names = [item["name"] for item in report["results"]]
    for expected in ("versi", "api_key", "provider", "fallback_chain", "checkpoints", "test_hook", "auto_update", "approval"):
        check(f"doctor covers {expected}", expected in names)
    report_text = format_doctor()
    check("doctor renders", "Rex Doctor" in report_text and "✔" in report_text or "○" in report_text)

    # API key must never be printed in full
    import rex.config as config_mod
    check("api_key masked in doctor", "api_key" in names)
    full_keys_leaked = [
        item for item in report["results"]
        if item["name"] == "api_key" and os.getenv("GEMINI_API_KEY", "") and os.getenv("GEMINI_API_KEY", "") in item["detail"]
    ]
    check("no full key in doctor output", not full_keys_leaked)

    # Cleanup: leave shadow repo in a sane state for other suites
    reset_shadow()

    print("\nReview checks ALL PASS")


if __name__ == "__main__":
    main()
