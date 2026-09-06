"""
rex.commands
============
Custom slash commands — user-defined Markdown prompts.

- Commands live in ``<workspace>/.rex/commands/*.md`` and extend the built-in
  slash commands of the TUI/CLI.
- The filename becomes the command name: ``.rex/commands/review.md`` adds
  ``/review``.
- Front-matter (``---`` block at the top) may declare a human-readable
  ``description``; it is stripped from the prompt sent to the agent.
- ``$ARGUMENTS`` in the body is replaced by whatever the user typed after
  the command (may be empty).
- The body is injected as a *user prompt* and executed by the normal agent
  loop — so every tool call it triggers still goes through mode checks,
  approval, and checkpoints. Custom commands never add new privileges.

Security notes:
- Only ``*.md`` files directly inside the commands dir are loaded (no
  recursion, no other extensions) — keeps the surface tiny.
- Command names are normalized: lowercase, ``[a-z0-9_-]`` only, max 32
  chars, and must not collide with built-in command names — built-ins
  always win so a file can never shadow ``/plan``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from rex.config import WORKSPACE_DIR

COMMANDS_DIRNAME = ".rex/commands"
MAX_COMMANDS = 100
MAX_BODY_CHARS = 8000
MAX_NAME_LEN = 32
ARGUMENTS_PLACEHOLDER = "$ARGUMENTS"

# Front-matter keys we understand (kept simple: no YAML dependency).
_FRONT_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_KEY_RE = re.compile(r"^\s*([a-z][a-z0-9-]*)\s*:\s*(.*?)\s*$", re.IGNORECASE)
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

# Reserved names — built-in slash commands (a file with one of these names
# is skipped; built-ins always win).
BUILTIN_COMMANDS = {
    "/plan", "/build", "/settings", "/theme", "/models", "/cost", "/init",
    "/commit", "/ask", "/imports", "/pr", "/stats", "/diff", "/doctor",
    "/test", "/checkpoints", "/undo", "/redo", "/help", "/exit", "/quit",
    "/voice", "/n8n", "/scheduler", "/anti-slop", "/files", "/sessions",
    "/new", "/use", "/delete", "/todos", "/resume", "/rewind", "/status",
    "/compare", "/export", "/skills", "/skill", "/plugins",
}


def commands_dir(workspace: Optional[Path] = None) -> Path:
    """Directory holding custom command files: ``<workspace>/.rex/commands``."""
    root = Path(workspace) if workspace else Path(WORKSPACE_DIR)
    return root / COMMANDS_DIRNAME


def _parse_front_matter(text: str) -> Tuple[Dict[str, str], str]:
    """
    Split an optional ``---`` front-matter block off the top of ``text``.

    Returns (meta, body). Unknown keys are ignored; malformed blocks are
    treated as plain body text (never an error).
    """
    match = _FRONT_RE.match(text)
    if not match:
        return {}, text
    meta: Dict[str, str] = {}
    for line in match.group(1).splitlines():
        key_match = _KEY_RE.match(line)
        if key_match:
            meta[key_match.group(1).lower()] = key_match.group(2)
    return meta, text[match.end():]


def _normalize_name(filename: str) -> str:
    """``Refactor-Core.md`` -> ``refactor-core``; invalid chars dropped."""
    stem = Path(filename).stem.lower()
    return re.sub(r"[^a-z0-9_-]", "-", stem)[:MAX_NAME_LEN]


def _valid_name(name: str) -> bool:
    return bool(name) and bool(_NAME_RE.match(name)) and len(name) <= MAX_NAME_LEN


def load_commands(workspace: Optional[Path] = None) -> Dict[str, dict]:
    """
    Load all custom commands from disk.

    Returns ``{"/name": {"name", "description", "prompt"}}`` — an empty dict
    when the directory is missing. Invalid files are skipped individually,
    never fatal (commands are a bonus, not a gate).
    """
    directory = commands_dir(workspace)
    result: Dict[str, dict] = {}
    if not directory.is_dir():
        return result
    try:
        files = sorted(directory.glob("*.md"))
    except OSError:
        return result
    for path in files:
        if len(result) >= MAX_COMMANDS:
            break
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        name = _normalize_name(path.name)
        if not _valid_name(name) or f"/{name}" in BUILTIN_COMMANDS:
            continue  # invalid or colliding with a built-in: skipped
        meta, body = _parse_front_matter(raw)
        prompt = body.strip()[:MAX_BODY_CHARS]
        if not prompt:
            continue
        result[f"/{name}"] = {
            "name": name,
            "description": str(meta.get("description", ""))[:200],
            "prompt": prompt,
        }
    return result


def expand_prompt(command: dict, arguments: str = "") -> str:
    """Substitute ``$ARGUMENTS`` in a command body with the user's text."""
    args = (arguments or "").strip()
    prompt = command["prompt"]
    if ARGUMENTS_PLACEHOLDER in prompt:
        return prompt.replace(ARGUMENTS_PLACEHOLDER, args)
    # No placeholder: append arguments so they are never silently dropped.
    return f"{prompt}\n{args}".strip() if args else prompt


def parse_input(text: str) -> Tuple[str, str]:
    """
    Split ``"/review some file.py"`` -> ``("/review", "some file.py")``.

    Returns ``("", text)`` for non-command text.
    """
    trimmed = (text or "").strip()
    if not trimmed.startswith("/"):
        return "", trimmed
    parts = trimmed.split(None, 1)
    command = parts[0].lower()
    arguments = parts[1] if len(parts) > 1 else ""
    return command, arguments


def format_help(commands: Dict[str, dict]) -> List[str]:
    """Human-readable help lines for ``/help``."""
    if not commands:
        return ["[dim]No custom commands — add .rex/commands/<nama>.md[/dim]"]
    lines = ["[b]Custom commands (.rex/commands/):[/b]"]
    for slash, info in sorted(commands.items()):
        desc = info.get("description") or ""
        suffix = f" [dim]— {desc}[/dim]" if desc else ""
        lines.append(f"  [b]{slash}[/b]{suffix}")
    return lines

