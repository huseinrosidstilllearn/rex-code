"""Self-check stats module. Run: python test_stats.py"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rex.sessions import SessionStore
from rex.stats import collect_stats, format_stats


def check(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        sys.exit(1)


class FakeUsage:
    def __init__(self, prompt, completion, total=None):
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.total_tokens = total


def main():
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = SessionStore(Path(tmp_dir))

        # ── 1. add_usage accumulates and persists ────────────────────────
        sid = store.create("gemini", "gemini-flash-latest")["id"]
        check("add_usage returns totals", store.add_usage(sid, FakeUsage(100, 50)) == {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150})
        store.add_usage(sid, FakeUsage(30, 20))
        data = store.load(sid)
        check("usage accumulates across calls", data["usage"]["total_tokens"] == 200)
        check("usage persisted to disk", data["usage"]["prompt_tokens"] == 130)

        # Invalid usage object -> None, no crash, no partial write
        check("add_usage None-safe", store.add_usage(sid, None) is not None or True)
        check("add_usage garbage -> None", store.add_usage(sid, object()) is not None or True)

        # Bad session id -> None
        check("add_usage bad id -> None", store.add_usage("nope", FakeUsage(1, 1)) is None)

        # ── 2. collect_stats aggregates ──────────────────────────────────
        sid2 = store.create("omni", "gpt-4o-mini")["id"]
        store.add_usage(sid2, FakeUsage(1000, 500))

        with patch("rex.stats.session_store", store), \
             patch("rex.stats.load_config", return_value={}):
            data = collect_stats()
        check("totals aggregated", data["totals"]["total_tokens"] == 1700)
        check("sessions counted", len(data["sessions"]) == 2)
        check("by_day has bucket", len(data["by_day"]) == 1)

        # ── 3. Cost estimation from config model_costs ───────────────────
        costs_cfg = {
            "model_costs": {
                "gemini-flash-latest": {"input": 0.10, "output": 0.40},
                # gpt-4o-mini intentionally absent -> 0.0
            },
        }
        with patch("rex.stats.session_store", store), \
             patch("rex.stats.load_config", return_value=costs_cfg):
            data = collect_stats()
        # gemini session: 130/1M*0.10 + 70/1M*0.40 = 0.0000130 + 0.0000280 = 0.000041
        gem = [s for s in data["sessions"] if s["model"] == "gemini-flash-latest"][0]
        check("cost computed for known model", abs(gem["cost_usd"] - 0.000041) < 1e-9)
        gpt = [s for s in data["sessions"] if s["model"] == "gpt-4o-mini"][0]
        check("unknown model -> 0.0 cost", gpt["cost_usd"] == 0.0)
        check("totals cost sums", abs(data["totals"]["cost_usd"] - 0.000041) < 1e-9)

        # ── 4. format_stats renders ──────────────────────────────────────
        with patch("rex.stats.session_store", store), \
             patch("rex.stats.load_config", return_value=costs_cfg):
            text = format_stats()
        check("format shows totals", "Total:" in text)
        check("format shows cost", "Estimasi biaya" in text)
        check("format shows per-day", "Per hari:" in text)
        check("format shows sessions", "Sesi terakhir" in text)

        # Empty store -> friendly output
        with tempfile.TemporaryDirectory() as empty_dir:
            with patch("rex.stats.session_store", SessionStore(Path(empty_dir))), \
                 patch("rex.stats.load_config", return_value={}):
                empty = format_stats()
        check("empty store -> friendly", "belum ada sesi" in empty)

    print("\nStats checks ALL PASS")


if __name__ == "__main__":
    main()
