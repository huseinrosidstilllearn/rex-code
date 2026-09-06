"""
rex.autogit
===========
AI-assisted git helpers: generate a conventional commit message or a PR
description from the *real* repository diff, then (for /commit) publish via
the existing git_publish pipeline — secret scan, approval gate, and
checkpoints all still apply.

No network beyond the configured LLM provider; everything is derived from
local git state.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional

from rex.logging_setup import log

MAX_DIFF_CHARS = 8000
MAX_SUBJECT = 72

_COMMIT_SYSTEM = (
    "Anda asisten git. Dari diff yang diberikan, susun SATU baris pesan commit "
    "gaya conventional commits: <tipe>: <deskripsi ringkas imperative>. "
    "Tipe: feat|fix|docs|style|refactor|test|chore. Maksimal 72 karakter. "
    "Tanpa backtick, tanpa nomor issue, tanpa penjelasan tambahan."
)

_PR_SYSTEM = (
    "Anda asisten git. Dari diff yang diberikan, tulis deskripsi pull request "
    "dalam markdown dengan struktur: ## Ringkasan (1-2 kalimat), "
    "## Perubahan (bullet list poin utama), ## Testing (cara menguji). "
    "Bahasa Indonesia, faktual, hanya dari isi diff."
)


def _run_git(args: List[str], cwd: Path, timeout: int = 20) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        timeout=timeout, encoding="utf-8", errors="replace",
    )


def collect_git_context(cwd: Optional[Path] = None, max_chars: int = MAX_DIFF_CHARS) -> Optional[str]:
    """
    Build the LLM context: staged+unstaged diff vs HEAD, branch, recent
    subjects, and file status. None when there is nothing to commit or git
    is unavailable. The diff is truncated to max_chars.
    """
    cwd = Path(cwd) if cwd else Path.cwd()
    try:
        status = _run_git(["status", "--porcelain", "--branch"], cwd)
        if status.returncode != 0:
            log.debug(f"autogit: git status failed: {status.stderr.strip()[:120]}")
            return None
        lines = [line for line in status.stdout.splitlines() if line.strip()]
        # First line is '## branch...'; the rest are changed files.
        if len(lines) <= 1:
            return None  # clean tree — nothing to describe

        diff = _run_git(["diff", "HEAD", "--no-color"], cwd)
        diff_text = diff.stdout.strip() if diff.returncode == 0 else "(diff tidak tersedia)"
        if len(diff_text) > max_chars:
            diff_text = diff_text[:max_chars] + "\n...[diff dipotong]"

        log_recent = _run_git(["log", "--oneline", "-5"], cwd)
        recent = log_recent.stdout.strip() if log_recent.returncode == 0 else "(log tidak tersedia)"

        branch = lines[0].lstrip("# ").strip() if lines else "(unknown)"
        files = "\n".join(lines[1:][:50])
        return (
            f"Branch: {branch}\n\nStatus:\n{files}\n\n"
            f"Commit terakhir (gaya yang sudah dipakai):\n{recent}\n\n"
            f"Diff:\n{diff_text}"
        )
    except Exception as exc:
        log.debug(f"autogit: context collection failed: {exc}")
        return None


def _ask_llm(system_prompt: str, user_prompt: str) -> Optional[str]:
    """One-shot LLM call on the active provider. None on failure."""
    try:
        from rex.providers.manager import get_llm_provider
        from rex.providers.gemini import GeminiProvider
        provider = get_llm_provider()
        if isinstance(provider, GeminiProvider):
            response = provider.chat_simple_with_usage(
                message=user_prompt, system_prompt=system_prompt, history=[],
            )
        else:
            response = provider.chat(
                messages=[{"role": "user", "content": user_prompt}],
                system_prompt=system_prompt,
            )
        text = str(getattr(response, "content", "") or "").strip()
        return text or None
    except Exception as exc:
        log.debug(f"autogit: LLM call failed: {exc}")
        return None


def _clean_subject(text: str) -> str:
    """First non-empty line, no backticks/quotes, capped at 72 chars."""
    for line in (text or "").splitlines():
        line = line.strip().strip("`").strip('"').strip("'").strip()
        if line:
            return line[:MAX_SUBJECT]
    return ""


def generate_commit_message(cwd: Optional[Path] = None) -> str:
    """Conventional commit subject from the real diff. Empty string on failure."""
    context = collect_git_context(cwd)
    if not context:
        return ""
    raw = _ask_llm(_COMMIT_SYSTEM, context)
    return _clean_subject(raw) if raw else ""


def generate_pr_description(cwd: Optional[Path] = None) -> str:
    """Markdown PR description from the real diff. Empty string on failure."""
    context = collect_git_context(cwd, max_chars=MAX_DIFF_CHARS * 2)
    if not context:
        return ""
    raw = _ask_llm(_PR_SYSTEM, context) or ""
    # Keep the LLM's markdown but drop accidental code fences around it.
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
    if raw.endswith("```"):
        raw = raw.rsplit("```", 1)[0]
    return raw.strip()


def commit_with_message(message: str, confirm: Callable[[str], bool]) -> str:
    """
    Confirm, then publish through tools.git_publish (secret scan, approval
    gate, checkpoints). Returns the tool's result text either way.
    """
    from rex.tools import git_publish
    message = (message or "").strip()
    if not message:
        return "DIBATALKAN: pesan commit kosong."
    if not confirm(message):
        return "DIBATALKAN: commit tidak dikonfirmasi."
    return git_publish(message)
