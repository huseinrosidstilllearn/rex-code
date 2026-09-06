"""Run every project self-check. Usage: python run_all_checks.py"""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
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
]


def main():
    for check in CHECKS:
        print(f"\n=== {check} ===", flush=True)
        result = subprocess.run([sys.executable, str(ROOT / check)], cwd=ROOT)
        if result.returncode:
            raise SystemExit(result.returncode)
    print(f"\nAll {len(CHECKS)} check suites PASS")


if __name__ == "__main__":
    main()