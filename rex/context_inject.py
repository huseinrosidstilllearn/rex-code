"""
rex.context_inject
==================
Project context injected into the system prompt:

- Project memory: ``REX.md`` in the working directory (+ optional global
  ``REX.md`` in the Rex data dir). The agent reads it every session, so
  users can state conventions, prohibitions, and test commands once.
- Layered project rules: ``.rex/rules/*.md`` in the project root (applies
  everywhere) and in immediate subfolders (applies when working there).
- Repo map: deterministic project overview (structure, languages, key
  files) — the cheap, always-fresh alternative to indexing.

Both are toggleable via ``config.json -> context`` and never raise:
context is a bonus, not a dependency.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from rex.config import DATA_DIR, load_config

MEMORY_FILENAME = "REX.md"

SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build",
    ".rex", ".idea", ".vscode", ".pytest_cache", ".mypy_cache", ".ruff_cache",
}

KEY_FILES = (
    "README.md", "requirements.txt", "pyproject.toml", "setup.py",
    "package.json", "Cargo.toml", "go.mod", "Dockerfile",
)

MAX_MEMORY_CHARS = 4000
MAX_MAP_CHARS = 2500
MAX_TOP_ENTRIES = 40

# Layered project rules (.rex/rules/*.md per folder)
RULES_DIR_PARTS = (".rex", "rules")
MAX_RULE_FILES = 12
MAX_RULE_FILE_CHARS = 4000
MAX_RULES_TOTAL_CHARS = 12_000


def global_memory_path() -> Path:
    return DATA_DIR / MEMORY_FILENAME


def project_memory_path(project_root: Optional[Path] = None) -> Path:
    root = Path(project_root) if project_root else Path.cwd()
    return root / MEMORY_FILENAME


def _read_capped(path: Path, cap: int) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    text = text.strip()
    if len(text) > cap:
        text = text[:cap] + "\n...[REX.md dipotong]"
    return text


def read_project_memory(project_root: Optional[Path] = None) -> str:
    return _read_capped(project_memory_path(project_root), MAX_MEMORY_CHARS)


def read_global_memory() -> str:
    return _read_capped(global_memory_path(), MAX_MEMORY_CHARS)


def create_rex_md(project_root: Optional[Path] = None) -> Tuple[bool, Path]:
    """
    Create a template REX.md. Never overwrites an existing file.
    Returns (created?, path).
    """
    path = project_memory_path(project_root)
    if path.exists():
        return False, path
    template = """# REX.md — Instruksi Proyek untuk Rex Code

Rex membaca file ini di awal setiap sesi. Tulis aturan yang harus selalu diikuti.

## Konteks Proyek
- (deskripsikan proyek ini secara singkat)

## Konvensi Kode
- Ikuti gaya kode yang sudah ada di file sekitar.
- Gunakan bahasa Indonesia untuk pesan commit.

## Larangan
- Jangan mengubah file konfigurasi tanpa diminta.
- Jangan commit langsung ke branch utama.

## Testing
- Jalankan test dengan: python run_all_checks.py
"""
    try:
        path.write_text(template, encoding="utf-8")
    except OSError:
        return False, path
    return True, path


def _language_stats(root: Path) -> List[Tuple[str, int]]:
    counts: Dict[str, int] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".git")]
        for filename in filenames:
            ext = os.path.splitext(filename)[1].lstrip(".").lower() or "other"
            counts[ext] = counts.get(ext, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:6]


def _count_files(dirpath: Path) -> int:
    """Count files under dirpath, skipping excluded directories."""
    count = 0
    for sub, dirnames, filenames in os.walk(dirpath):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        count += len(filenames)
    return count


def _top_level_lines(root: Path) -> List[str]:
    try:
        entries = sorted(root.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except OSError:
        return []
    lines: List[str] = []
    for entry in entries[:MAX_TOP_ENTRIES]:
        if entry.name in SKIP_DIRS:
            continue
        if entry.is_dir():
            try:
                file_count = _count_files(entry)
            except OSError:
                file_count = 0
            lines.append(f"- {entry.name}/ ({file_count} files)")
        else:
            lines.append(f"- {entry.name}")
    if len(entries) > MAX_TOP_ENTRIES:
        lines.append(f"- ... (+{len(entries) - MAX_TOP_ENTRIES} entries lainnya)")
    return lines


def build_repo_map(project_root: Optional[Path] = None) -> str:
    """Deterministic project overview. Empty string when the dir is unreadable."""
    root = Path(project_root) if project_root else Path.cwd()
    if not root.is_dir():
        return ""
    top = _top_level_lines(root)
    if not top:
        return ""
    stats = _language_stats(root)
    langs = ", ".join(f"{ext}={count}" for ext, count in stats)
    keys = [name for name in KEY_FILES if (root / name).exists()]
    sections = [f"Project root: {root.name}", "Top-level:", *top]
    if langs:
        sections.append(f"Languages: {langs}")
    if keys:
        sections.append(f"Key files: {', '.join(keys)}")
    text = "\n".join(sections)
    if len(text) > MAX_MAP_CHARS:
        text = text[:MAX_MAP_CHARS] + "\n...[repo map dipotong]"
    return text


def collect_rules(project_root: Optional[Path] = None) -> List[Tuple[str, str]]:
    """
    Layered project rules: ``<folder>/.rex/rules/*.md``.

    Layer 1 = project root (applies everywhere); layer 2 = immediate
    subfolders (apply when working inside that folder). Returns
    ``[(scope_label, text)]`` top-down, alphabetical per folder. Markdown
    files only, capped per file and in total. Never raises.
    """
    root = Path(project_root) if project_root else Path.cwd()
    if not root.is_dir():
        return []
    result: List[Tuple[str, str]] = []

    def _gather(rules_dir: Path, scope: str) -> None:
        if len(result) >= MAX_RULE_FILES or not rules_dir.is_dir():
            return
        try:
            files = sorted(rules_dir.glob("*.md"), key=lambda p: p.name.lower())
        except OSError:
            return
        for path in files:
            if len(result) >= MAX_RULE_FILES:
                return
            text = _read_capped(path, MAX_RULE_FILE_CHARS)
            if text:
                result.append((scope, text))

    _gather(root.joinpath(*RULES_DIR_PARTS), "seluruh proyek")
    total = sum(len(text) for _, text in result)
    try:
        children = sorted(
            (d for d in root.iterdir() if d.is_dir() and d.name not in SKIP_DIRS),
            key=lambda p: p.name.lower(),
        )
    except OSError:
        children = []
    for child in children:
        if total >= MAX_RULES_TOTAL_CHARS or len(result) >= MAX_RULE_FILES:
            break
        before = len(result)
        _gather(child.joinpath(*RULES_DIR_PARTS), f"folder {child.name}/")
        total += sum(len(text) for _, text in result[before:])
    return result


def build_context_prefix(mode: str = "") -> str:
    """
    Build the extra context block appended to the system prompt.
    Honors the ``context`` config toggles. Never raises.
    """
    try:
        cfg = load_config()
        settings = cfg.get("context") or {}
    except Exception:
        settings = {}
    blocks: List[str] = []

    if settings.get("project_memory", True):
        project = read_project_memory()
        global_mem = read_global_memory()
        try:
            same_file = project_memory_path().resolve() == global_memory_path().resolve()
        except OSError:
            same_file = False
        if project and global_mem and not same_file:
            blocks.append(f"=== Project Instructions (REX.md proyek) ===\n{project}")
            blocks.append(f"=== Global Instructions (REX.md global) ===\n{global_mem}")
        else:
            if project:
                blocks.append(f"=== Project Instructions (REX.md) ===\n{project}")
            elif global_mem:
                blocks.append(f"=== Global Instructions (REX.md global) ===\n{global_mem}")

    if settings.get("rules", True):
        rule_pairs = collect_rules()
        if rule_pairs:
            rendered = "\n\n".join(
                f"[Berlaku: {scope}]\n{text}" for scope, text in rule_pairs
            )
            blocks.append(f"=== Project Rules (.rex/rules/) ===\n{rendered}")

    if settings.get("skills", True):
        try:
            from rex.skills import format_skills_overview
            overview = format_skills_overview()
        except Exception:
            overview = ""
        if overview:
            blocks.append(f"=== Skills Tersedia ===\n{overview}")

    if settings.get("repo_map", True):
        repo_map = build_repo_map()
        if repo_map:
            blocks.append(f"=== Repo Map ===\n{repo_map}")

    if not blocks:
        return ""
    return "\n\n" + "\n\n".join(blocks)
