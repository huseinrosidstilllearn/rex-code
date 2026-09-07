"""Run every project self-check. Usage: python run_all_checks.py

Hardened runner:
- every suite gets a hard timeout (a hang can no longer wedge the run),
- all suites execute even when one fails (full picture, not just first error),
- a failure summary + non-zero exit code at the end (CI gate friendly).
"""

import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TIMEOUT_SEC = 300  # per-suite cap; full local run is ~2 min for all 43
CHECKS = [
    "test_foundations.py",
    "test_streaming.py",
    "test_openai_compatible.py",
    "test_sessions.py",
    "test_config.py",
    "test_sandbox.py",
    "test_git_publish.py",
    "test_voice.py",
    "test_plugins.py",
    "test_webhooks.py",
    "test_updates.py",
    "test_scheduler.py",
    "test_approval.py",
    "test_retry.py",
    "test_context.py",
    "test_headless.py",
    "test_checkpoints.py",
    "test_compaction.py",
    "test_mcp.py",
    "test_security.py",
    "test_failover.py",
    "test_review.py",
    "test_stats.py",
    "test_autogit.py",
    "test_vision.py",
    "test_ecosystem.py",
    "test_codeindex.py",
    "test_phase9.py",
    "test_packaging.py",
    "test_assets.py",
    "test_commands.py",
    "test_todos.py",
    "test_diffs.py",
    "test_agentguard.py",
    "test_usage.py",
    "test_hooks.py",
    "test_status.py",
    "test_websearch.py",
    "test_export.py",
    "test_skills.py",
    "test_app_controller.py",
    "test_desktop.py",
    "test_cli_ui.py",
]


def main() -> int:
    failures: list[tuple[str, str]] = []
    for check in CHECKS:
        print(f"\n=== {check} ===", flush=True)
        started = time.monotonic()
        try:
            result = subprocess.run(
                [sys.executable, str(ROOT / check)],
                cwd=ROOT,
                timeout=TIMEOUT_SEC,
            )
        except subprocess.TimeoutExpired:
            print(f"!! {check} TIMED OUT after {TIMEOUT_SEC}s — treated as failure", flush=True)
            failures.append((check, f"timeout after {TIMEOUT_SEC}s"))
            continue
        elapsed = time.monotonic() - started
        if result.returncode:
            print(f"!! {check} FAILED (exit {result.returncode}) after {elapsed:.1f}s", flush=True)
            failures.append((check, f"exit code {result.returncode}"))
        else:
            print(f"ok {check} — {elapsed:.1f}s", flush=True)

    if failures:
        print(f"\n{len(failures)}/{len(CHECKS)} suite(s) FAILED:", flush=True)
        for name, why in failures:
            print(f"  - {name}: {why}", flush=True)
        return 1
    print(f"\nAll {len(CHECKS)} check suites PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())