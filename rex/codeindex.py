"""
rex.codeindex
=============
Local code intelligence for Rex Code — zero services, zero embeddings.

- ``build_index()`` walks the workspace (SKIP_DIRS excluded) and records
  symbols (def/class/function) with line numbers per text file.
- ``query()`` searches symbols and file names/contents; ``/ask`` renders it.
- ``import_graph()`` maps imports between local modules (Python AST +
  regex fallback for JS/TS-style imports) for repo map v2.

The index is a plain JSON file at ``<workspace>/.rex/index.json`` — rebuilt
when stale (mtime/size changes) or on demand. Everything stays local.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

INDEX_REL = Path(".rex") / "index.json"
SKIP_DIRS = {
    ".git", ".rex", "__pycache__", "node_modules", ".venv", "venv",
    "dist", "build", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".idea", ".vscode",
}
TEXT_SUFFIXES = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rb", ".rs",
    ".c", ".h", ".cpp", ".hpp", ".cs", ".php", ".sh", ".ps1", ".md",
    ".json", ".yaml", ".yml", ".toml", ".html", ".css",
}
MAX_FILE_BYTES = 1_000_000
MAX_INDEX_CHARS = 4000  # rendering cap for /ask

# JS/TS-style import regex (import x from 'y' / require('y') / from 'y')
_JS_IMPORT_RE = re.compile(
    r"(?:import\s+[^'\"]*?from\s*|import\s*\(\s*|require\s*\(\s*)['\"]([^'\"]+)['\"]"
)


def _workspace() -> Path:
    from rex.config import WORKSPACE_DIR
    return Path(WORKSPACE_DIR)


def index_path() -> Path:
    return _workspace() / INDEX_REL


def _iter_files(root: Path):
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        yield path


def _python_symbols(source: str) -> List[Dict]:
    """AST-extracted defs/classes with line numbers (never raises)."""
    symbols: List[Dict] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return symbols
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.append({
                "name": node.name,
                "kind": "class" if isinstance(node, ast.ClassDef) else "def",
                "line": node.lineno,
            })
    return symbols


_GENERIC_DEF_RE = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?(?:function|class)\s+([A-Za-z_$][\w$]*)")


def _generic_symbols(source: str) -> List[Dict]:
    symbols = []
    for line_number, line in enumerate(source.splitlines(), 1):
        match = _GENERIC_DEF_RE.match(line)
        if match:
            symbols.append({"name": match.group(1), "kind": "def", "line": line_number})
    return symbols


def _local_imports(source: str, path: Path, root: Path) -> List[str]:
    """Module names imported that also exist as local files."""
    local: set = set()

    if path.suffix == ".py":
        try:
            tree = ast.parse(source)
        except SyntaxError:
            tree = None
        if tree is not None:
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        local.add(alias.name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    local.add(node.module)
        # Python-style: 'from rex import x' -> rex/x.py
        sep = "."
    else:
        for match in _JS_IMPORT_RE.finditer(source):
            module = match.group(1)
            if module.startswith("./"):
                module = module[2:]
            local.add(module)
        sep = "/"

    resolved = []
    for module in local:
        rel = module.replace(sep, "/")
        for candidate in (rel, f"{rel}.py", f"{rel}.js", f"{rel}.ts", f"{rel}/__init__.py", f"{rel}/index.js"):
            if (root / candidate).is_file():
                resolved.append(rel)
                break
    return sorted(resolved)


def build_index(force: bool = False, root: Optional[Path] = None) -> Dict:
    """
    Build (or refresh) the index. Skips work when the stored signature
    (file path+mtime+size list) is unchanged, unless force=True.
    """
    root = Path(root) if root else _workspace()
    signature = {}
    files: Dict[str, Dict] = {}
    for path in _iter_files(root):
        try:
            stat = path.stat()
            rel = path.relative_to(root).as_posix()
        except (OSError, ValueError):
            continue
        signature[rel] = [int(stat.st_mtime), stat.st_size]
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        entry: Dict = {"symbols": _python_symbols(source) if path.suffix == ".py" else _generic_symbols(source)}
        imports = _local_imports(source, path, root)
        if imports:
            entry["imports"] = imports
        files[rel] = entry

    index = {"files": files, "signature": signature}
    store = (Path(root) if root else _workspace()) / INDEX_REL

    if not force:
        try:
            stored = json.loads(store.read_text(encoding="utf-8"))
            if stored.get("signature") == signature and isinstance(stored.get("files"), dict):
                return stored
        except Exception:
            pass  # missing/corrupt index -> rebuild

    try:
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(json.dumps(index), encoding="utf-8")
    except OSError:
        pass  # index is a bonus; never fatal
    return index


def query(index: Dict, text: str, limit: int = 30, root: Optional[Path] = None) -> List[Dict]:
    """
    Search symbols (prefix/substring on name), then file names, then file
    contents. Results: {file, line?, kind, snippet}. The content pass reads
    from root (defaults to the live workspace).
    """
    text = (text or "").strip()
    if not text:
        return []
    lowered = text.lower()
    results: List[Dict] = []
    seen_files = set()

    # 1. Symbols
    for rel, entry in sorted((index.get("files") or {}).items()):
        for symbol in entry.get("symbols") or []:
            if lowered in symbol["name"].lower():
                results.append({"file": rel, "line": symbol["line"], "kind": symbol["kind"], "match": symbol["name"]})
                seen_files.add(rel)
                if len(results) >= limit:
                    return results

    # 2. File names
    for rel in sorted(index.get("files") or {}):
        if lowered in rel.lower() and rel not in seen_files:
            results.append({"file": rel, "kind": "file", "match": rel})
            if len(results) >= limit:
                return results

    # 3. File contents (first matching lines)
    root = Path(root) if root else _workspace()
    for rel in sorted(index.get("files") or {}):
        if rel in seen_files:
            continue
        try:
            full = root / rel
            with open(full, "r", encoding="utf-8", errors="replace") as handle:
                for line_number, line in enumerate(handle, 1):
                    if lowered in line.lower():
                        results.append({"file": rel, "line": line_number, "kind": "content", "match": line.strip()[:160]})
                        if len(results) >= limit:
                            return results
                        break  # one hit per file in content pass
        except OSError:
            continue
    return results


def import_graph(index: Dict) -> Dict[str, List[str]]:
    """{module file -> [local files it imports]} from the index."""
    graph = {}
    for rel, entry in (index.get("files") or {}).items():
        imports = entry.get("imports") or []
        if imports:
            graph[rel] = imports
    return graph


def format_ask(index: Dict, question: str, root: Optional[Path] = None) -> str:
    """/ask rendering: ranked hits with locations."""
    hits = query(index, question, root=root)
    if not hits:
        return f"Tidak ditemukan: '{question}'"
    lines = [f"Hasil untuk '{question}':"]
    for hit in hits[:15]:
        if hit["kind"] in ("def", "class"):
            lines.append(f"  {hit['file']}:{hit['line']}  {hit['kind']} {hit['match']}")
        elif hit["kind"] == "file":
            lines.append(f"  {hit['file']}  (nama file cocok)")
        else:
            lines.append(f"  {hit['file']}:{hit['line']}  {hit['match']}")
    if len(hits) > 15:
        lines.append(f"  … dan {len(hits) - 15} hasil lain")
    return "\n".join(lines)


def format_import_graph(index: Dict, max_edges: int = 60) -> str:
    """Repo map v2 rendering: module -> imported local modules."""
    graph = import_graph(index)
    if not graph:
        return "(tidak ada import antar-modul lokal yang terdeteksi)"
    lines = ["Graf import (repo map v2):"]
    edges = 0
    for source in sorted(graph):
        targets = graph[source]
        lines.append(f"  {source} -> {', '.join(targets)}")
        edges += len(targets)
        if edges >= max_edges:
            lines.append("  …[dipotong]")
            break
    return "\n".join(lines)


# ── @file:symbol references + @ autocomplete ─────────────────────────

MAX_SYMBOL_SPAN_LINES = 400
MAX_COMPLETIONS = 6


def locate_symbol_span(source: str, symbol: str, python: bool = True) -> Optional[tuple]:
    """
    Locate a def/class/function by name in source; returns the 1-based
    inclusive (start, end) line span, or None when not found.

    For Python the block ends at the first later line whose indentation is
    not deeper than the definition line (so a class span includes its
    methods); for other languages it ends where the next symbol starts.
    The span is capped at MAX_SYMBOL_SPAN_LINES lines.
    """
    symbol = (symbol or "").strip()
    if not symbol:
        return None
    lines = source.splitlines()
    if not lines:
        return None
    symbols = _python_symbols(source) if python else _generic_symbols(source)
    lowered = symbol.lower()
    matches = [s for s in symbols if s["name"].lower() == lowered]
    if not matches:
        matches = [s for s in symbols if lowered in s["name"].lower()]
    if not matches:
        return None
    start = min(s["line"] for s in matches)

    if python:
        def_line = lines[start - 1]
        base_indent = len(def_line) - len(def_line.lstrip())
        end = len(lines)
        for offset in range(start, len(lines)):
            line = lines[offset]
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip())
            if indent <= base_indent:
                end = offset  # 1-based inclusive: previous line
                break
    else:
        later = [s["line"] for s in symbols if s["line"] > start]
        end = (min(later) - 1) if later else len(lines)
    end = min(end, start - 1 + MAX_SYMBOL_SPAN_LINES)
    while end > start and not lines[end - 1].strip():
        end -= 1  # don't trail blank lines behind the block
    return (start, max(start, end))


def complete_reference(index: Dict, token: str, limit: int = MAX_COMPLETIONS) -> List[str]:
    """
    Candidates for an ``@``-token as the user types (token excludes '@').

    ``@cor``            -> files whose path contains 'cor'
    ``@rex/core.py``    -> exact/partial file paths
    ``@rex/core.py:loc``-> symbols in that file matching 'loc'
    Returns at most ``limit`` suggestions; empty when nothing matches.
    """
    token = (token or "").strip()
    if not token:
        return []
    files = index.get("files") or {}
    if ":" in token:
        path_part, _, sym = token.partition(":")
        rels = [rel for rel in sorted(files) if _path_matches(rel, path_part)][:3]
        out: List[str] = []
        for rel in rels:
            for symbol in files[rel].get("symbols") or []:
                if sym.lower() in symbol["name"].lower():
                    out.append(f"{rel}:{symbol['name']}")
                    if len(out) >= limit:
                        return out
        return out
    return [rel for rel in sorted(files) if _path_matches(rel, token)][:limit]


def _path_matches(rel: str, token: str) -> bool:
    lowered = token.lower()
    return rel.lower().startswith(lowered) or f"/{lowered}" in rel.lower() or lowered in Path(rel).name.lower()
