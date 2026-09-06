"""Self-check usage meter (rex/usage.py + core integration). Run: python test_usage.py"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rex.usage import UsageMeter, coerce_usage
from rex.sessions import SessionStore


def check(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        sys.exit(1)


class FakeUsage:
    def __init__(self, prompt, completion, total=None):
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.total_tokens = total


CFG = {
    "active_provider": "gemini",
    "active_model": "m1",
    "model_costs": {
        "m1": {"input": 0.10, "output": 0.40},
        "m2": {"input": 1.00, "output": 2.00},
    },
}


def patched_cfg(cfg=CFG):
    return patch("rex.usage.load_config", return_value=dict(cfg)), patch(
        "rex.usage.normalize_config", side_effect=lambda c: c
    )


def main():
    with tempfile.TemporaryDirectory() as tmp_dir:
        # ── 1. coerce_usage normalization ────────────────────────────────
        check("coerce None -> None", coerce_usage(None) is None)
        check(
            "coerce object attrs",
            coerce_usage(FakeUsage(100, 50)) == {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        )
        check(
            "coerce keeps explicit total",
            coerce_usage(FakeUsage(100, 50, 200))["total_tokens"] == 200,
        )
        check(
            "coerce dict",
            coerce_usage({"prompt_tokens": 10, "completion_tokens": 5})
            == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )
        check("coerce garbage -> None", coerce_usage("nope") is None)
        check("coerce non-numeric -> None", coerce_usage({"prompt_tokens": "x"}) is None)
        check(
            "coerce clamps negatives",
            coerce_usage({"prompt_tokens": -5, "completion_tokens": 10})["prompt_tokens"] == 0,
        )

        # ── 2. accumulate + totals ───────────────────────────────────────
        p1, p2 = patched_cfg()
        with p1, p2:
            meter = UsageMeter()
        check("meter starts empty", meter.totals()["total_tokens"] == 0)
        check("accumulate returns entry", meter.accumulate(FakeUsage(100, 50))["total_tokens"] == 150)
        meter.accumulate(FakeUsage(30, 20))
        check("accumulate sums across calls", meter.totals()["total_tokens"] == 200)
        check("accumulate None no-op", meter.accumulate(None) is None)
        check("accumulate garbage no-op", meter.accumulate(object()) is None)
        meter.accumulate({"prompt_tokens": 1, "completion_tokens": 1}, model="m2")
        check("per-model bucket", meter.by_model["m2"]["total_tokens"] == 2)
        check("totals cross-model", meter.totals()["total_tokens"] == 202)
        meter.reset()
        check("reset clears", meter.totals()["total_tokens"] == 0 and not meter.by_model)

        # ── 3. cost estimation from config model_costs ───────────────────
        p1, p2 = patched_cfg()
        with p1, p2:
            meter = UsageMeter()  # active model m1: in 0.10 / out 0.40 per 1M
        meter.accumulate(FakeUsage(1_000_000, 500_000))
        check("cost uses model rates", abs(meter.cost_usd() - 0.30) < 1e-9)
        meter.accumulate(FakeUsage(1_000_000, 0), model="m2")  # 1.00 per 1M in
        check("cost sums across models", abs(meter.cost_usd() - 1.30) < 1e-9)

        p1, p2 = patched_cfg({"active_model": "unknown-model", "model_costs": {}})
        with p1, p2:
            meter = UsageMeter()
        meter.accumulate(FakeUsage(1000, 1000))
        check("unknown model costs $0", meter.cost_usd() == 0.0)

        # ── 4. refresh_config ────────────────────────────────────────────
        p1, p2 = patched_cfg()
        with p1, p2:
            meter = UsageMeter()
            check("refresh picks active model", meter._model == "m1")
        with patch("rex.usage.load_config", side_effect=RuntimeError("broken")), patch(
            "rex.usage.normalize_config", side_effect=lambda c: c
        ):
            meter.refresh_config()
        check("refresh survives broken config", meter._model == "" and meter._costs == {})

        # ── 5. formatting ────────────────────────────────────────────────
        p1, p2 = patched_cfg()
        with p1, p2:
            meter = UsageMeter()
        summary = meter.format_summary()
        check("summary shows zero totals", "total 0 token" in summary)
        meter.accumulate(FakeUsage(1500, 301))
        check("summary shows totals + cost", "1,801 token" in meter.format_summary() and "$0.0003" in meter.format_summary())
        meter.accumulate(FakeUsage(10, 10), model="m2")
        check("summary breakdown with 2 models", "[m1" in meter.format_summary() and "m2" in meter.format_summary())
        check("footer empty state", meter.reset() is None and meter.format_footer() == "")
        meter.accumulate(FakeUsage(1801, 0))
        check("footer short form", meter.format_footer() == "1.8k tok · ~$0.0002")
        meter.accumulate(FakeUsage(940, 0))
        check("footer raw below 1k", meter.format_footer() == "2.7k tok · ~$0.0003")
        check("footer carries cost estimate", "$0.0003" in meter.format_footer())

        # ── 6. agent integration (backward-compatible total_usage) ──────
        from rex.core import RexAgent

        store = SessionStore(Path(tmp_dir) / "sessions")
        with patch("rex.core.session_store", store):
            agent = RexAgent()
            agent._accumulate_usage(FakeUsage(100, 50))
            check("agent.total_usage compat", agent.total_usage["total_tokens"] == 150)
            check("agent meter shares state", agent.usage.totals()["total_tokens"] == 150)
            agent._accumulate_usage(None)
            check("agent accumulate None-safe", agent.total_usage["total_tokens"] == 150)
            agent._accumulate_usage({"prompt_tokens": 5, "completion_tokens": 5})
            check("agent accumulate dict", agent.total_usage["total_tokens"] == 160)
            agent.reset()
            check("agent reset clears usage", agent.total_usage["total_tokens"] == 0)

            # Session store persistence still wired through the meter
            sid = store.create("gemini", "m1")["id"]
            agent2 = RexAgent(session_id=sid)
            agent2._accumulate_usage(FakeUsage(10, 5))
            check("usage persisted to session store", store.load(sid)["usage"]["total_tokens"] == 15)

        # ── 7. token_budget normalization ────────────────────────────────
        from rex.config import normalize_config

        check("budget default 0", normalize_config({})["token_budget"] == 0)
        check("budget string accepted", normalize_config({"token_budget": "5000"})["token_budget"] == 5000)
        check("budget float floored", normalize_config({"token_budget": 2500.7})["token_budget"] == 2500)
        check("budget negative -> 0", normalize_config({"token_budget": -5})["token_budget"] == 0)
        check("budget garbage -> 0", normalize_config({"token_budget": "abc"})["token_budget"] == 0)
        check("budget bool rejected", normalize_config({"token_budget": True})["token_budget"] == 0)

        # ── 8. budget status thresholds ─────────────────────────────────
        p1, p2 = patched_cfg({"active_model": "m1", "model_costs": {}, "token_budget": 100})
        with p1, p2:
            meter = UsageMeter()
        check("budget loaded from config", meter.budget == 100)
        check("status ok at start", meter.status() == "ok")
        meter.accumulate(FakeUsage(79, 0))
        check("status ok below 80%", meter.status() == "ok")
        meter.accumulate(FakeUsage(1, 0))
        check("status warning at exactly 80%", meter.status() == "warning")
        meter.accumulate(FakeUsage(19, 0))
        check("status warning below 100%", meter.status() == "warning")
        meter.accumulate(FakeUsage(1, 0))
        check("status exceeded at 100%", meter.status() == "exceeded")
        meter.accumulate(FakeUsage(50, 0))
        check("status exceeded above 100%", meter.status() == "exceeded")
        meter.budget = 0
        check("status off without budget", meter.status() == "off")

        # ── 9. budget messages + formatting ─────────────────────────────
        meter.budget = 100
        meter.reset()
        meter.accumulate(FakeUsage(85, 0))
        check("warning message has numbers", "85/100" in meter.warning_message() and "(85%)" in meter.warning_message())
        meter.accumulate(FakeUsage(15, 0))
        stop = meter.stop_message()
        check("stop message names config key", "token_budget" in stop and "config.json" in stop)
        check("summary includes budget", "budget 100/100 (100%)" in meter.format_summary())
        check("footer includes budget pct", "100% budget" in meter.format_footer())

        # ── 10. agent hard stop when budget exhausted ───────────────────
        import rex.core as core_mod
        from rex.core import RexAgent
        from rex.providers.base import LLMResponse, Usage

        class FakeRouter:
            def __init__(self, usage=None):
                self._usage = usage

            def chat(self, messages, system_prompt, tools=None):
                return LLMResponse(content="ok", usage=self._usage)

        def budget_patches():
            return [
                patch.object(core_mod, "build_context_prefix", return_value=""),
                patch("rex.core.maybe_compact", return_value=(None, False)),
                patch("rex.core.load_config", return_value={"max_history_messages": 40, "stream_enabled": False, "max_steps": 5, "anti_slop_enabled": False}),
                patch("rex.usage.load_config", return_value={"token_budget": 100, "active_model": "m1"}),
                patch("rex.usage.normalize_config", side_effect=lambda c: c),
            ]

        with patch("rex.core.session_store", store):
            agent = RexAgent()
            agent.usage.budget = 100
            agent.usage.accumulate(FakeUsage(120, 0))
            events = []
            all_patches = [patch.object(core_mod, "get_llm_provider_with_fallback", side_effect=RuntimeError("provider must not be called"))] + budget_patches()
            with all_patches[0], all_patches[1], all_patches[2], all_patches[3], all_patches[4], all_patches[5]:
                out = agent.run("halo", on_step=events.append)
            check("exhausted budget stops the run", "BUDGET TOKEN HABIS" in out)
            kinds = [e.event_type for e in events]
            check("stop emits usage_alert + done", "usage_alert" in kinds and "done" in kinds and "tool_call" not in kinds)
            alert = next(e for e in events if e.event_type == "usage_alert")
            check("stop alert flagged exceeded", alert.data.get("status") == "exceeded")

            # ── 11. agent warning + post-round exceeded ─────────────────
            agent.reset()
            agent.usage.accumulate(FakeUsage(80, 0))  # exactly 80% -> warning
            events = []
            all_patches = [patch.object(core_mod, "get_llm_provider_with_fallback", return_value=(FakeRouter(), [("gemini", "m1")]))] + budget_patches()
            with all_patches[0], all_patches[1], all_patches[2], all_patches[3], all_patches[4], all_patches[5]:
                out = agent.run("halo", on_step=events.append)
            check("warning run still answers", out == "ok")
            alert = next(e for e in events if e.event_type == "usage_alert")
            check("warning alert fired", alert.data.get("status") == "warning" and "80/100" in alert.data.get("message", ""))

            agent.reset()
            agent.usage.accumulate(FakeUsage(99, 0))  # round pushes past 100%
            events = []
            all_patches = [patch.object(core_mod, "get_llm_provider_with_fallback", return_value=(FakeRouter(Usage(5, 5)), [("gemini", "m1")]))] + budget_patches()
            with all_patches[0], all_patches[1], all_patches[2], all_patches[3], all_patches[4], all_patches[5]:
                out = agent.run("halo", on_step=events.append)
            check("crossing 100% mid-run still completes", out == "ok")
            alert = next(e for e in events if e.event_type == "usage_alert")
            check("post-round exceeded alert", alert.data.get("status") == "exceeded")
            all_patches = budget_patches()
            with all_patches[0], all_patches[1], all_patches[2], all_patches[3], all_patches[4]:
                check("next run now stops", "BUDGET TOKEN HABIS" in agent.run("lagi"))

    print("\nAll usage checks PASS")


if __name__ == "__main__":
    main()
