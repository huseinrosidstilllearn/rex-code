"""
rex.compaction
==============
Context compaction: when the message history grows past a token budget,
older turns are summarized **by the active LLM** into a single memory
note instead of being crudely truncated. Falls back to plain trimming
when no provider is available or summarization fails.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from rex.config import load_config

SUMMARY_PREFIX = "[Ringkasan sesi sebelumnya]"

SUMMARY_PROMPT = """Ringkas percakapan berikut menjadi poin-poin penting yang dibutuhkan untuk melanjutkan pekerjaan:
- Tujuan/user intent utama
- Keputusan & preferensi pengguna
- File yang dibuat/diubah/dihapus (sebutkan path)
- Perintah yang dijalankan dan hasil pentingnya
- Langkah berikutnya yang belum selesai

Maksimal 250 kata. Tanpa basa-basi."""


def estimate_tokens(messages: List[Dict]) -> int:
    """Cheap heuristic: ~4 characters per token."""
    total_chars = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            total_chars += len(content)
        total_chars += len(str(message.get("tool_calls", "")))
    return total_chars // 4


def _split_history(messages: List[Dict], keep_recent: int) -> Optional[Tuple[List[Dict], List[Dict]]]:
    """Split into (old, recent) at a message boundary; None when nothing to compact."""
    compactable = [m for m in messages if m.get("role") in ("user", "assistant", "tool")]
    if len(compactable) <= keep_recent:
        return None
    boundary = len(messages) - keep_recent
    old, recent = messages[:boundary], messages[boundary:]
    if not old or not recent:
        return None
    return old, recent


def _messages_to_text(messages: List[Dict], max_chars: int = 12000) -> str:
    lines = []
    total = 0
    for message in messages:
        role = message.get("role", "?")
        content = str(message.get("content", ""))[:1500]
        line = f"{role}: {content}"
        total += len(line)
        if total > max_chars:
            lines.append("...[riwayat lebih lanjut dipotong]")
            break
        lines.append(line)
    return "\n".join(lines)


def _llm_summary(old_messages: List[Dict]) -> Optional[str]:
    """Ask the active provider for a summary. Returns None on any failure."""
    try:
        from rex.providers.manager import get_llm_provider
        provider = get_llm_provider()
        conversation = _messages_to_text(old_messages)
        if hasattr(provider, "chat_simple_with_usage"):
            response = provider.chat_simple_with_usage(
                f"{SUMMARY_PROMPT}\n\n---\n{conversation}",
                system_prompt="Anda adalah asisten yang meringkas riwayat sesi coding.",
            )
            text = (response.content or "").strip()
        else:
            response = provider.chat(messages=[], system_prompt="Ringkas riwayat sesi coding.")
            text = (getattr(response, "content", "") or "").strip()
        return text or None
    except Exception:
        return None


def maybe_compact(
    messages: List[Dict],
    system_prompt: Optional[str] = None,
) -> Tuple[List[Dict], bool]:
    """
    Return (possibly compacted messages, was_compacted?).
    No-ops below budget, for short histories, or when summarization fails.
    """
    cfg = load_config()
    context_cfg = cfg.get("context") or {}
    budget = int(context_cfg.get("max_context_tokens", 60000) or 60000)
    if estimate_tokens(messages) <= budget:
        return messages, False

    keep_recent = max(6, int(cfg.get("max_history_messages", 40)) // 2)
    split = _split_history(messages, keep_recent)
    if split is None:
        return messages, False
    old, recent = split

    summary = _llm_summary(old)
    if not summary:
        return messages, False  # fallback: caller keeps its existing trim behavior

    note = {"role": "assistant", "content": f"{SUMMARY_PREFIX}\n{summary}"}
    return [note] + recent, True
