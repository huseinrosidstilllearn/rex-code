"""Self-check for headless runner. Run: python test_headless.py"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rex.headless as headless
from rex.headless import format_result_json, format_result_text, run_headless
from rex.approval import _get_settings, _override_settings, set_override_settings, set_provider


def check(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        sys.exit(1)


class FakeAgent:
    def __init__(self, session_id=None):
        self.session_id = session_id or ""
        self.total_usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}

    def run(self, prompt, on_step=None):
        return f"jawaban: {prompt}"


def main():
    set_override_settings(None)
    set_provider(None)

    # ── Successful one-shot run (mocked agent) ────────────────────────
    with patch.object(headless, "RexAgent", FakeAgent):
        result = run_headless("halo dunia", mode="plan")
    check("ok true", result["ok"] is True)
    check("response echoed", result["response"] == "jawaban: halo dunia")
    check("mode set", result["mode"] == "plan")
    check("usage accumulated", result["usage"]["total_tokens"] == 15)
    check("elapsed measured", result["elapsed_ms"] >= 0)
    check("no provider_failed", result.get("provider_failed") is False)

    # ── Safety posture: default denies destructive actions (during run) ─
    set_override_settings(None)
    set_provider(None)
    captured = {}
    class ProbingAgent(FakeAgent):
        def run(self, prompt, on_step=None):
            from rex.approval import request_approval as _ra
            captured["settings"] = dict(_get_settings())
            captured["destructive_denied"] = _ra("run_command", "anything") is False
            return "ok"
    with patch.object(headless, "RexAgent", ProbingAgent):
        run_headless("tes")
    check("default: approval forced on during run", captured["settings"].get("enabled") is True)
    check("default: empty actions = all gated", captured["settings"].get("actions") == [])
    check("default: destructive denied during run", captured["destructive_denied"] is True)
    check("default: deny provider attached", headless._deny_all_provider("x", "y") is False)

    # settings cleaned up after run
    check("override cleared after run", _override_settings is None)

    # ── yolo: no forced posture ───────────────────────────────────────
    set_override_settings(None)
    set_provider(None)
    with patch.object(headless, "RexAgent", FakeAgent):
        run_headless("tes", yolo=True)
    check("yolo: override not set", _override_settings is None)
    set_override_settings(None)
    set_provider(None)

    # ── Provider failure flagged ──────────────────────────────────────
    class FailingProviderAgent(FakeAgent):
        def run(self, prompt, on_step=None):
            return "Provider gagal memproses permintaan. Periksa konfigurasi dan logs/rex.log."
    with patch.object(headless, "RexAgent", FailingProviderAgent):
        result = run_headless("tes")
    check("provider failure flagged", result.get("provider_failed") is True)

    # ── Agent crash -> structured error, no exception escape ──────────
    class ExplodingAgent(FakeAgent):
        def run(self, prompt, on_step=None):
            raise RuntimeError("boom")
    with patch.object(headless, "RexAgent", ExplodingAgent):
        result = run_headless("tes")
    check("crash -> ok false", result["ok"] is False)
    check("crash -> error recorded", "RuntimeError" in result.get("error", ""))

    # ── Formatters ────────────────────────────────────────────────────
    ok_result = {"ok": True, "response": "teks jawaban"}
    check("text format", format_result_text(ok_result) == "teks jawaban")
    parsed = json.loads(format_result_json(ok_result))
    check("json format round-trip", parsed["response"] == "teks jawaban")
    check("text error format", "[ERROR]" in format_result_text({"ok": False, "error": "x"}))

    print("\nHeadless checks PASS")


if __name__ == "__main__":
    main()
