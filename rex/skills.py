"""
rex.skills
==========
On-demand skills: reusable instruction packs in
``<workspace>/.rex/skills/<name>/SKILL.md``.

- Discovery is cheap: only the front-matter (``name``, ``description``)
  or first heading line is read up front; that compact listing is
  injected into the system prompt so the model knows what exists.
- The full body is loaded on demand — via the ``load_skill`` tool when
  the model decides a skill applies, or ``/skill <name>`` in the TUI.

Fail-open everywhere: no skills dir, a broken file, or a bad
front-matter simply means "fewer skills", never an error.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

SKILLS_DIRNAME = ".rex/skills"
SKILL_FILENAME = "SKILL.md"
MAX_SKILLS = 24
MAX_NAME_LEN = 40
MAX_DESCRIPTION_CHARS = 120
MAX_BODY_CHARS = 12_000

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def skills_dir(workspace: Optional[Path] = None) -> Path:
    root = Path(workspace) if workspace else Path.cwd()
    return root / SKILLS_DIRNAME


def _normalize_name(folder: str) -> str:
    stem = folder.strip().lower()
    return re.sub(r"[^a-z0-9_-]", "-", stem)[:MAX_NAME_LEN]


def _first_meaningful_line(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped
    return ""


def _parse_skill(path: Path) -> Optional[Dict[str, str]]:
    """Read one SKILL.md: (name, description, body). Returns None when unusable."""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    meta: Dict[str, str] = {}
    body = raw
    if raw.lstrip().startswith("---"):
        # lightweight front-matter (same shape as custom commands)
        from rex.commands import _parse_front_matter
        meta, body = _parse_front_matter(raw)
    name = _normalize_name(meta.get("name") or path.parent.name)
    if not _NAME_RE.match(name):
        return None
    if not body.strip():
        return None  # an empty instruction pack is not a skill
    description = str(meta.get("description") or "").strip()
    if not description:
        description = _first_meaningful_line(body)
    return {
        "name": name,
        "description": description[:MAX_DESCRIPTION_CHARS],
        "path": str(path),
        "body": body.strip()[:MAX_BODY_CHARS],
    }


def load_skills(workspace: Optional[Path] = None) -> Dict[str, Dict[str, str]]:
    """
    Discover all skills. Returns ``{name: {name, description, path, body}}``
    sorted by name; body included (reading is local and cheap).
    """
    directory = skills_dir(workspace)
    result: Dict[str, Dict[str, str]] = {}
    if not directory.is_dir():
        return result
    try:
        candidates = sorted(directory.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return result
    for folder in candidates:
        if len(result) >= MAX_SKILLS:
            break
        if not folder.is_dir():
            continue
        parsed = _parse_skill(folder / SKILL_FILENAME)
        if parsed and parsed["name"] not in result:
            result[parsed["name"]] = parsed
    return result


def get_skill(name: str, workspace: Optional[Path] = None) -> Optional[Dict[str, str]]:
    """One skill by name (normalized); None when unknown."""
    return load_skills(workspace).get(_normalize_name(name))


def format_skills_overview(workspace: Optional[Path] = None) -> str:
    """Compact listing injected into the system prompt; '' when none."""
    skills = load_skills(workspace)
    if not skills:
        return ""
    lines = ["Skill tersedia (muat dengan tool load_skill saat relevan):"]
    for skill in skills.values():
        lines.append(f"- {skill['name']}: {skill['description']}")
    return "\n".join(lines)
