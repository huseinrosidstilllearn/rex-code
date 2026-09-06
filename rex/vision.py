"""
rex.vision
==========
Multimodal input + @file context injection.

Users prefix a path with ``@`` in any message (CLI or TUI):

    lihat @screenshots/bug.png dan perbaiki
    jelaskan isi @rex/core.py

- Image files (png/jpg/jpeg/gif/webp, max 5 MB) become *attachments* and are
  sent to the Gemini provider as vision parts.
- Text files (max 20k chars) are inlined into the prompt as fenced content.
- Anything else (missing, too large, binary) is dropped with a note so the
  model (and user) know what happened.

Extraction is shared by every entry point: ``extract_references()`` returns
(prompt, attachments, notes) and the agent layer converts attachments into
provider parts. Nothing here raises to the user.
"""

from __future__ import annotations

import base64
import mimetypes
import re
from pathlib import Path
from typing import Dict, List, Tuple

from rex.logging_setup import log

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_TEXT_CHARS = 20_000

# @path token: no whitespace inside; allows ./ ../ subdirs and common name chars.
AT_REF_RE = re.compile(r"@([^\s@]+)")


def extract_references(text: str, base_dir: Path = None) -> Tuple[str, List[Path], List[str]]:
    """
    Pull @file references out of the user message.

    Returns (clean_prompt, image_attachments, notes):
      - clean_prompt: the message with @tokens removed (kept readable)
      - image_attachments: readable image files (validated, size-capped)
      - notes: human-readable lines about dropped references
    """
    if base_dir is None:
        from rex.config import WORKSPACE_DIR
        base_dir = Path(WORKSPACE_DIR)
    if not isinstance(text, str) or "@" not in text:
        return text, [], []

    attachments: List[Path] = []
    notes: List[str] = []
    consumed_spans: List[Tuple[int, int]] = []

    for match in AT_REF_RE.finditer(text):
        token = match.group(1)
        candidate = (base_dir / token).resolve()
        if not candidate.is_file():
            notes.append(f"@{token}: file tidak ditemukan")
            consumed_spans.append(match.span())
            continue
        suffix = candidate.suffix.lower()
        if suffix in IMAGE_SUFFIXES:
            try:
                if candidate.stat().st_size > MAX_IMAGE_BYTES:
                    notes.append(f"@{token}: gambar terlalu besar (maks 5 MB)")
                else:
                    attachments.append(candidate)
            except OSError:
                notes.append(f"@{token}: tidak bisa dibaca")
        elif suffix in {".env", ".pem", ".key"} or candidate.name in {"config.json", ".env"}:
            notes.append(f"@{token}: file sensitif tidak di-inline")
        else:
            try:
                with open(candidate, "rb") as raw_handle:
                    head = raw_handle.read(1024)
                if b"\x00" in head:
                    notes.append(f"@{token}: file biner tidak di-inline")
                    consumed_spans.append(match.span())
                    continue
                raw = candidate.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                notes.append(f"@{token}: file biner tidak di-inline")
                consumed_spans.append(match.span())
                continue
            content = raw[:MAX_TEXT_CHARS]
            if len(raw) > MAX_TEXT_CHARS:
                content += "\n...[dipotong]"
            notes.append(f"Isi @{token}:\n```\n{content}\n```")
        consumed_spans.append(match.span())

    # Remove consumed @tokens, keep everything else intact.
    clean = text
    for start, end in sorted(consumed_spans, reverse=True):
        clean = clean[:start] + clean[end:]
    clean = re.sub(r"  +", " ", clean).strip()

    # Inline notes after the user's message so the model sees them as context.
    inlined = [n for n in notes if n.startswith("Isi @")]
    dropped = [n for n in notes if not n.startswith("Isi @")]
    if inlined or dropped:
        clean = (clean + "\n\n" + "\n\n".join(inlined + dropped)).strip()
    return clean, attachments, notes


def gemini_parts(attachments: List[Path]) -> List[Dict[str, str]]:
    """
    Convert image files to {mime_type, data(base64)} dicts — the neutral
    shape the Gemini provider turns into google.genai Parts.
    """
    parts: List[Dict[str, str]] = []
    for path in attachments:
        try:
            mime = mimetypes.guess_type(str(path))[0] or "image/png"
            data = base64.b64encode(path.read_bytes()).decode("ascii")
            parts.append({"mime_type": mime, "data": data})
        except Exception as exc:
            log.debug(f"vision: failed to encode {path}: {exc}")
    return parts


def build_gemini_message(message: str, attachments: List[Path]):
    """
    Return the send_message payload for Gemini: a plain string when there
    are no images, otherwise a [text, Part, ...] list.
    """
    parts = gemini_parts(attachments)
    if not parts:
        return message
    try:
        from google.genai import types
        converted = [
            types.Part.from_bytes(data=base64.b64decode(p["data"]), mime_type=p["mime_type"])
            for p in parts
        ]
        return [message or "(lihat gambar terlampir)", *converted]
    except Exception as exc:
        log.debug(f"vision: gemini parts unavailable ({exc}) — text-only fallback")
        return message + "\n\n(gambar terlampir tidak dapat dikirim)"
