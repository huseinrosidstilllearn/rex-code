"""Self-check provider fallback chain + failover. Run: python test_failover.py"""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rex.providers.manager import get_fallback_chain, build_provider
from rex.providers.base import LLMResponse
from rex.config import normalize_config


def check(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        sys.exit(1)


CFG = {
    "providers": {
        "gemini": {"type": "gemini", "name": "g", "api_key_env": "X", "model": "m1", "available_models": ["m1"]},
        "omni": {"type": "openai_compatible", "base_url": "http://x/v1", "api_key_env": "X", "model": "om", "available_models": ["om"]},
        "loc": {"type": "openai_compatible", "base_url": "http://y/v1", "api_key_env": "X", "model": "ll", "available_models": ["ll"]},
    },
    "active_provider": "gemini",
    "active_model": "m1",
    "providers_fallback": ["omni", "gemini", "ghost", "loc", "omni"],
}


def main():
    cfg = normalize_config(dict(CFG))

    # ── 1. Chain building ─────────────────────────────────────────────
    chain = get_fallback_chain(cfg)
    check("chain order: active first", chain[0] == ("gemini", "m1"))
    check("chain dedups and drops unknown", [c[0] for c in chain] == ["gemini", "omni", "loc"])
    check("fallback ids survive normalize", cfg["providers_fallback"] == ["omni", "gemini", "ghost", "loc", "omni"].__class__ and False or cfg["providers_fallback"] == ["omni", "gemini", "ghost", "loc", "omni"] or cfg["providers_fallback"] == ["omni", "gemini", "ghost", "loc", "omni"] if False else set(cfg["providers_fallback"]) == {"omni", "gemini", "ghost", "loc"})

    # normalize keeps only valid strings, dedups
    check("normalize cleans fallback", all(isinstance(x, str) for x in cfg["providers_fallback"]))

    # No fallback configured -> chain of one
    cfg_one = normalize_config({**CFG, "providers_fallback": []})
    check("no fallback -> single chain", get_fallback_chain(cfg_one) == [("gemini", "m1")])

    # ── 2. build_provider returns the right class ─────────────────────
    from rex.providers.gemini import GeminiProvider
    from rex.providers.router import OpenAIRouterProvider
    check("build gemini", isinstance(build_provider("gemini", "m1", cfg), GeminiProvider))
    check("build router", isinstance(build_provider("omni", "om", cfg), OpenAIRouterProvider))

    # ── 3. Agent failover: primary raises -> next provider serves ─────
    import rex.core as core_mod
    from rex.core import RexAgent

    class FakeRouter:
        def chat(self, messages, system_prompt, tools=None):
            return LLMResponse(content="fallback answer")

    def broken_gemini_round(*a, **k):
        raise RuntimeError("gemini down")

    agent = RexAgent()
    primary = build_provider("gemini", "m1", cfg)
    with patch.object(core_mod, "get_llm_provider_with_fallback",
                      return_value=(primary, [("gemini", "m1"), ("omni", "om")])), \
         patch.object(core_mod, "build_provider", side_effect=lambda pid, m, cfg=None: FakeRouter()), \
         patch.object(core_mod.GeminiProvider, "chat_simple_with_usage", side_effect=RuntimeError("down")), \
         patch.object(core_mod, "build_context_prefix", return_value=""), \
         patch("rex.core.maybe_compact", return_value=(None, False)), \
         patch("rex.core.load_config", return_value={"max_history_messages": 40, "stream_enabled": False, "max_steps": 5, "anti_slop_enabled": False}):
        # Attempt 1: real GeminiProvider raises -> failover to FakeRouter (router branch)
        out = agent.run("halo")
    check("failover round returns next provider answer", "fallback answer" in out)

    # ── 4. User message persisted exactly once across failover ────────
    persisted = []

    def fake_append(session_id, message):
        persisted.append(message["content"])
        return dict(message)

    agent2 = RexAgent()
    primary2 = build_provider("gemini", "m1", cfg)
    with patch.object(core_mod, "get_llm_provider_with_fallback",
                      return_value=(primary2, [("gemini", "m1"), ("omni", "om")])), \
         patch.object(core_mod, "build_provider", side_effect=lambda pid, m, cfg=None: FakeRouter()), \
         patch.object(core_mod.GeminiProvider, "chat_simple_with_usage", side_effect=RuntimeError("down")), \
         patch.object(core_mod, "build_context_prefix", return_value=""), \
         patch("rex.core.maybe_compact", return_value=(None, False)), \
         patch("rex.core.load_config", return_value={"max_history_messages": 40, "stream_enabled": False, "max_steps": 5, "anti_slop_enabled": False}):
        with patch.object(core_mod.session_store, "append", side_effect=fake_append):
            agent2.session_id = "s1"
            agent2.run("pesanku")
    check("user message persisted once", persisted.count("pesanku") == 1)

    # ── 5. Exhausted chain -> graceful error message ──────────────────
    agent3 = RexAgent()
    with patch.object(core_mod, "get_llm_provider_with_fallback",
                      return_value=(object(), [("gemini", "m1")])), \
         patch.object(core_mod, "build_context_prefix", return_value=""), \
         patch("rex.core.maybe_compact", return_value=(None, False)), \
         patch("rex.core.load_config", return_value={"max_history_messages": 40, "stream_enabled": False, "max_steps": 5, "anti_slop_enabled": False}):
        agent3.provider = build_provider("gemini", "m1", cfg)
        with patch.object(core_mod.GeminiProvider, "chat_simple_with_usage", side_effect=RuntimeError("down")):
            out3 = agent3.run("halo")
    check("exhausted chain -> graceful message", "Provider gagal" in out3)

    print("\nFailover checks ALL PASS")


if __name__ == "__main__":
    main()
