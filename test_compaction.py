"""Self-check for context compaction. Run: python test_compaction.py"""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rex.compaction as compaction
from rex.compaction import estimate_tokens, maybe_compact
from rex.providers.base import Usage


def check(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        sys.exit(1)


def big_history(turns=30, chars=4000):
    messages = []
    for i in range(turns):
        messages.append({"role": "user", "content": f"pertanyaan {i} " + "x" * chars})
        messages.append({"role": "assistant", "content": f"jawaban {i} " + "y" * chars})
    return messages


class FakeProvider:
    def __init__(self):
        self.last_message = None

    def chat_simple_with_usage(self, message, system_prompt, **kwargs):
        self.last_message = message
        class Resp:
            content = "- tujuan: tes\n- file: a.py diubah\n- langkah: lanjut review"
            usage = Usage(100, 20, 120)
        return Resp()


def main():
    # ── Token estimation ──────────────────────────────────────────────
    small = [{"role": "user", "content": "a" * 400}]
    check("estimate ~chars/4", 90 <= estimate_tokens(small) <= 110)
    empty = []
    check("empty history -> 0 tokens", estimate_tokens(empty) == 0)

    # ── Below budget: untouched ───────────────────────────────────────
    messages = big_history(turns=3)
    with patch.object(compaction, "load_config", return_value={"context": {"max_context_tokens": 60000}, "max_history_messages": 40}):
        result, did = maybe_compact(messages)
    check("below budget untouched", result is messages and did is False)

    # ── Above budget: LLM summary replaces old turns ──────────────────
    provider = FakeProvider()
    messages = big_history(turns=30)
    with patch.object(compaction, "load_config", return_value={"context": {"max_context_tokens": 1000}, "max_history_messages": 40}), \
         patch("rex.providers.manager.get_llm_provider", return_value=provider):
        result, did = maybe_compact(messages)
    check("above budget compacted", did is True)
    check("compacted smaller", len(result) < len(messages))
    check("summary note present", compaction.SUMMARY_PREFIX in result[0]["content"])
    check("summary requested from LLM", "Ringkas" in (provider.last_message or ""))
    check("recent turns preserved", any("jawaban 29" in str(m.get("content", "")) for m in result))
    check("old raw turns dropped", not any("pertanyaan 0 " in str(m.get("content", "")) for m in result))

    # ── LLM failure: fallback (no compaction, no crash) ───────────────
    def broken_provider():
        raise RuntimeError("no network")
    messages = big_history(turns=30)
    with patch.object(compaction, "load_config", return_value={"context": {"max_context_tokens": 1000}, "max_history_messages": 40}), \
         patch("rex.providers.manager.get_llm_provider", side_effect=broken_provider):
        result, did = maybe_compact(messages)
    check("llm failure -> fallback no compaction", did is False and result is messages)

    # ── Short history: nothing to split even above budget ─────────────
    short = [{"role": "user", "content": "x" * 6000}]
    with patch.object(compaction, "load_config", return_value={"context": {"max_context_tokens": 100}, "max_history_messages": 40}):
        result, did = maybe_compact(short)
    check("short history skip", did is False)

    print("\nCompaction checks PASS")


if __name__ == "__main__":
    main()
