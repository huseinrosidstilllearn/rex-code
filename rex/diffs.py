"""
rex.diffs
=========
Unified-diff parsing and applying — no external dependency.

The agent produces patches via the ``apply_patch`` tool; this module turns
a standard unified diff (the format ``git diff`` / ``diff -u`` emits) into
structured hunks and applies them to workspace files.

Supported:
- ``--- a/<path>`` / ``+++ b/<path>`` headers (``/dev/null`` = create/delete)
- ``@@ -l,c +l,c @@`` hunk headers (count-free forms tolerated)
- Context ' ', addition '+', removal '-' lines; '\\ No newline at end of
  file' markers ignored
- Multiple files in one patch

Not supported (rejected with a clear error instead of guessing):
- renames/copies, binary patches, git mode-change lines, ``diff --git``
  extended headers only when they contradict the ---/+++ paths

Apply rules:
- BUILD mode only (enforced by the tool layer, same as write_file)
- hunks apply top-to-bottom with fuzzy context matching: exact match first,
  then a small window scan (like ``patch(1)`` default fuzz) so a model's
  slightly drifted context still lands; hard mismatch = abort with the
  hunk number, nothing is written
- every apply runs the standard approval gate + checkpoint, via the same
  helper write_file/edit_file use
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_OLD_RE = re.compile(r"^--- (?:a/)?(.+)$")
_NEW_RE = re.compile(r"^\+\+\+ (?:b/)?(.+)$")
# Lines git emits that carry no patch content.
_META_PREFIXES = ("diff --git", "index ", "old mode", "new mode",
                  "new file mode", "deleted file mode", "similarity index",
                  "rename from", "rename to", "copy from", "copy to",
                  "Binary files", "GIT binary patch", "\\ No newline")

MAX_FILES = 50
MAX_LINES = 5000
FUZZ_WINDOW = 64  # how far up/down a hunk may drift from its stated position


class DiffError(ValueError):
    """Raised when a patch is malformed or does not apply."""


def _strip_meta(line: str) -> bool:
    """True when the line is git metadata we ignore."""
    return any(line.startswith(p) for p in _META_PREFIXES)


def parse_diff(patch: str) -> List[dict]:
    """
    Parse a unified diff into ``[{old_path, new_path, hunks}]``.

    Each hunk: ``{old_start, new_start, lines: [(tag, text)]}`` with tag in
    ``' ', '+', '-'``. Raises DiffError on structural problems.
    """
    if not isinstance(patch, str) or not patch.strip():
        raise DiffError("Patch kosong.")
    raw_lines = patch.splitlines()
    if len(raw_lines) > MAX_LINES:
        raise DiffError(f"Patch terlalu besar ({len(raw_lines)} baris, maks {MAX_LINES}).")

    files: List[dict] = []
    current: Optional[dict] = None
    hunk: Optional[dict] = None
    for lineno, line in enumerate(raw_lines, start=1):
        if _strip_meta(line):
            continue
        if line.startswith("--- "):
            current = {
                "old_path": _OLD_RE.match(line).group(1) if _OLD_RE.match(line) else line[4:],
                "new_path": None,
                "hunks": [],
            }
            files.append(current)
            hunk = None
            continue
        if line.startswith("+++ "):
            if current is None:
                raise DiffError(f"Baris {lineno}: '+++' tanpa '---' sebelumnya.")
            match = _NEW_RE.match(line)
            current["new_path"] = match.group(1) if match else line[4:]
            continue
        hunk_match = _HUNK_RE.match(line)
        if hunk_match:
            if current is None:
                raise DiffError(f"Baris {lineno}: hunk tanpa header file (---/+++).")
            old_start = int(hunk_match.group(1))
            old_count = int(hunk_match.group(2)) if hunk_match.group(2) is not None else 1
            new_start = int(hunk_match.group(3))
            new_count = int(hunk_match.group(4)) if hunk_match.group(4) is not None else 1
            hunk = {"old_start": old_start, "old_start_count": old_count,
                    "new_start": new_start, "new_start_count": new_count, "lines": []}
            current["hunks"].append(hunk)
            continue
        if line[:1] in (" ", "+", "-"):
            if hunk is None:
                # Tolerate leading garbage between files (patch(1) style
                # free text) — skip it.
                continue
            hunk["lines"].append((line[:1], line[1:]))
            continue
        # Anything else between hunks: tolerate as free text (patch(1) does).
    if len(files) > MAX_FILES:
        raise DiffError(f"Terlalu banyak file ({len(files)}, maks {MAX_FILES}).")
    for entry in files:
        if entry["new_path"] is None:
            raise DiffError(f"File '{entry['old_path']}' tanpa header '+++'.")
        for hunk in entry["hunks"]:
            _validate_hunk(hunk)
    return files


def _validate_hunk(hunk: dict) -> None:
    """Check a parsed hunk's line counts against its header."""
    old = sum(1 for tag, _ in hunk["lines"] if tag in (" ", "-"))
    new = sum(1 for tag, _ in hunk["lines"] if tag in (" ", "+"))
    if old != hunk["old_start_count"] or new != hunk["new_start_count"]:
        # patch(1) tolerates miscounts; so do we, but keep the header values
        # for matching. Log-free by design: apply() fails if it truly can't.
        hunk["old_start_count"] = old
        hunk["new_start_count"] = new


def _normalized_file_paths(entry: dict) -> Tuple[Optional[str], Optional[str]]:
    """Resolve /dev/null + a/b prefixes into (old, new) workspace paths."""
    old = entry["old_path"]
    new = entry["new_path"]
    old = None if old in ("/dev/null", "") else old
    new = None if new in ("/dev/null", "") else new
    return old, new


def _match_at(lines: List[str], hunk: dict, pos: int) -> bool:
    """True when the hunk's old side matches ``lines`` starting at ``pos``."""
    idx = pos
    for tag, text in hunk["lines"]:
        if tag == "+":
            continue
        if idx >= len(lines) or lines[idx] != text:
            return False
        idx += 1
    return True


def _apply_hunks(lines: List[str], hunks: List[dict]) -> List[str]:
    """
    Apply hunks top-to-bottom with a bounded fuzzy window.

    Hard mismatch raises DiffError naming the hunk — the caller discards
    everything, so a failed patch never half-writes a file.
    """
    result = list(lines)
    offset = 0  # cumulative shift from earlier hunks in this file
    for number, hunk in enumerate(hunks, start=1):
        target = hunk["old_start"] - 1 + offset
        found = None
        lo = max(0, target - FUZZ_WINDOW)
        hi = min(len(result), target + FUZZ_WINDOW + 1)
        candidates = [target] + [p for p in range(lo, hi) if p != target]
        for pos in candidates:
            if _match_at(result, hunk, pos):
                found = pos
                break
        if found is None:
            raise DiffError(
                f"Hunk #{number} (baris {hunk['old_start']}) tidak cocok dengan file."
            )
        replacement: List[str] = []
        idx = found
        for tag, text in hunk["lines"]:
            if tag == " ":
                replacement.append(result[idx]); idx += 1
            elif tag == "-":
                idx += 1
            elif tag == "+":
                replacement.append(text)
        result = result[:found] + replacement + result[idx:]
        offset += sum(1 for tag, _ in hunk["lines"] if tag == "+") - \
                  sum(1 for tag, _ in hunk["lines"] if tag == "-")
    return result


def apply_to_text(text: str, hunks: List[dict]) -> str:
    """Apply hunks to a string, returning the new text (or raising DiffError)."""
    lines = text.splitlines()
    patched = _apply_hunks(lines, hunks)
    trailing_newline = text.endswith("\n")
    return "\n".join(patched) + ("\n" if trailing_newline or not text else "")


def build_new_file(hunks: List[dict]) -> str:
    """Assemble the content of a brand-new file from '+' hunks."""
    parts: List[str] = []
    for hunk in hunks:
        for tag, text in hunk["lines"]:
            if tag in ("+", " "):
                parts.append(text)
    return "\n".join(parts) + ("\n" if parts else "")


def deleted_file(entry: dict) -> bool:
    """True when the entry describes a deletion (new side is /dev/null)."""
    old, new = _normalized_file_paths(entry)
    return new is None and old is not None


def created_file(entry: dict) -> bool:
    """True when the entry describes a creation (old side is /dev/null)."""
    old, new = _normalized_file_paths(entry)
    return old is None and new is not None
