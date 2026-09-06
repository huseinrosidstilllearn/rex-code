"""
rex.usage
=========
Session-scoped token usage meter and cost estimate.

One ``UsageMeter`` per agent instance: every response's usage is fed in
by ``RexAgent._accumulate_usage``; the meter keeps cumulative totals, a
per-model breakdown, and a running cost estimate from
``config.json -> "model_costs"`` (the same USD-per-1M-token convention
as ``rex.stats`` — unknown models simply cost $0, never a guess).

Everything is local; nothing leaves the machine.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from rex.config import load_config, normalize_config
from rex.stats import _estimate_cost, _model_costs


def coerce_usage(usage: Any) -> Optional[Dict[str, int]]:
    """
    Normalize one response's usage into non-negative ints; None when unusable.

    Accepts attribute objects (``LLMResponse.usage``) or plain dicts.
    A missing ``total_tokens`` falls back to prompt + completion.
    """
    if usage is None:
        return None
    if isinstance(usage, dict):
        raw_prompt = usage.get("prompt_tokens")
        raw_completion = usage.get("completion_tokens")
        raw_total = usage.get("total_tokens")
    else:
        raw_prompt = getattr(usage, "prompt_tokens", None)
        raw_completion = getattr(usage, "completion_tokens", None)
        raw_total = getattr(usage, "total_tokens", None)
    # Objects with no usage fields at all (garbage) are rejected outright —
    # otherwise every random object would silently count as 0 tokens.
    if raw_prompt is None and raw_completion is None and raw_total is None:
        return None
    prompt = raw_prompt or 0
    completion = raw_completion or 0
    total = raw_total
    try:
        prompt = max(0, int(prompt))
        completion = max(0, int(completion))
    except (TypeError, ValueError):
        return None
    try:
        total = max(0, int(total)) if total is not None else prompt + completion
    except (TypeError, ValueError):
        total = prompt + completion
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total}


def _short_count(count: int) -> str:
    """Compact number for the status bar: 940 -> '940', 1801 -> '1.8k'."""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1000:
        return f"{count / 1000:.1f}k"
    return str(count)


class UsageMeter:
    """Cumulative token/cost accounting for one agent session."""

    def __init__(self) -> None:
        self.by_model: Dict[str, Dict[str, int]] = {}
        self._model = ""
        self._costs: Dict[str, Dict[str, float]] = {}
        self.refresh_config()

    # ── accumulation ──────────────────────────────────────────────────
    def accumulate(self, usage: Any, model: Optional[str] = None) -> Optional[Dict[str, int]]:
        """Add one response's usage; returns the normalized entry or None."""
        entry = coerce_usage(usage)
        if entry is None:
            return None
        name = model or self._model or "unknown"
        bucket = self.by_model.setdefault(
            name, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        )
        for key, value in entry.items():
            bucket[key] += value
        return entry

    def refresh_config(self) -> None:
        """Re-read the active model and cost rates from config.json."""
        try:
            cfg = normalize_config(load_config())
            self._model = str(cfg.get("active_model", "") or "")
            self._costs = _model_costs(cfg)
        except Exception:
            self._model, self._costs = "", {}

    # ── totals ────────────────────────────────────────────────────────
    def totals(self) -> Dict[str, int]:
        """Cumulative totals across every model seen this session."""
        sums = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        for bucket in self.by_model.values():
            for key in sums:
                sums[key] += bucket[key]
        return sums

    def cost_usd(self) -> float:
        """Running cost estimate (0.0 when no model has configured rates)."""
        return sum(
            _estimate_cost(name, bucket["prompt_tokens"], bucket["completion_tokens"], self._costs)
            for name, bucket in self.by_model.items()
        )

    def reset(self) -> None:
        """Clear all accumulation (new session / explicit reset)."""
        self.by_model = {}

    # ── formatting ────────────────────────────────────────────────────
    def format_summary(self) -> str:
        """One-line /cost summary with the per-model breakdown."""
        totals = self.totals()
        parts = [
            f"prompt {totals['prompt_tokens']:,}",
            f"completion {totals['completion_tokens']:,}",
            f"total {totals['total_tokens']:,} token",
            f"~${self.cost_usd():.4f}",
        ]
        line = " · ".join(parts)
        if len(self.by_model) > 1:
            breakdown = ", ".join(
                f"{name} {_short_count(bucket['total_tokens'])}"
                for name, bucket in sorted(self.by_model.items())
            )
            line += f"  [{breakdown}]"
        return line

    def format_footer(self) -> str:
        """Compact status-bar form: ``1.8k tok · $0.0021`` ('' when unused)."""
        totals = self.totals()
        if totals["total_tokens"] <= 0:
            return ""
        return f"{_short_count(totals['total_tokens'])} tok · ~${self.cost_usd():.4f}"
