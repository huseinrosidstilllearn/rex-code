"""Self-check vision module (@file + image attachments). Run: python test_vision.py"""

import base64
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rex.vision import (
    AT_REF_RE,
    build_gemini_message,
    extract_references,
    gemini_parts,
)


def check(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        sys.exit(1)


# Minimal valid PNG (1x1 transparent pixel)
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def main():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws = Path(tmp_dir)
        (ws / "shot.png").write_bytes(PNG_BYTES)
        (ws / "notes.txt").write_text("isi catatan penting\n", encoding="utf-8")
        (ws / "config.json").write_text("{}", encoding="utf-8")
        (ws / "data.bin").write_bytes(b"\x00\x01\x02binary")

        # ── 1. Text @file inlining ───────────────────────────────────────
        prompt, images, notes = extract_references("jelaskan @notes.txt dong", base_dir=ws)
        check("text file inlined", any("isi catatan penting" in n for n in notes))
        check("no images from text file", images == [])
        check("token removed from user sentence", prompt.startswith("jelaskan dong"))
        check("user text preserved", "jelaskan" in prompt and "dong" in prompt)

        # ── 2. Image @file → attachment ──────────────────────────────────
        prompt, images, notes = extract_references("lihat @shot.png", base_dir=ws)
        check("image attached", images == [ws / "shot.png"])
        check("image not inlined as text", not any("PNG" in n for n in notes))

        # ── 3. Sensitive + missing + binary ──────────────────────────────
        prompt, images, notes = extract_references("lihat @config.json dan @missing.txt", base_dir=ws)
        check("sensitive not inlined", any("sensitif" in n for n in notes))
        check("missing noted", any("tidak ditemukan" in n for n in notes))
        prompt, images, notes = extract_references("baca @data.bin", base_dir=ws)
        check("binary dropped with note", any("biner" in n for n in notes))
        check("no crash on binary", images == [])

        # ── 4. No references → passthrough ───────────────────────────────
        prompt, images, notes = extract_references("halo tanpa referensi", base_dir=ws)
        check("no refs -> unchanged prompt", prompt == "halo tanpa referensi")
        check("no refs -> no attachments", images == [] and notes == [])

        # ── 5. gemini_parts conversion ───────────────────────────────────
        parts = gemini_parts([ws / "shot.png"])
        check("parts carry mime", parts and parts[0]["mime_type"] == "image/png")
        check("parts carry base64", base64.b64decode(parts[0]["data"]) == PNG_BYTES)

        # ── 6. build_gemini_message shapes ───────────────────────────────
        check("no images -> plain string", build_gemini_message("halo", []) == "halo")

        fake_types = MagicMock()
        fake_types.Part.from_bytes.side_effect = lambda data, mime_type: ("PART", data, mime_type)
        with patch.dict(sys.modules, {"google.genai.types": fake_types}), \
             patch("google.genai.types", fake_types, create=True):
            payload = build_gemini_message("lihat ini", [ws / "shot.png"])
        check("with images -> list payload", isinstance(payload, list))
        check("payload starts with text", payload and payload[0] == "lihat ini")
        check("payload contains part", len(payload) == 2)

        # Fallback when google.genai unavailable
        with patch.dict(sys.modules, {"google": None, "google.genai": None}):
            payload = build_gemini_message("lihat ini", [ws / "shot.png"])
        check("no sdk -> text fallback", isinstance(payload, str) and "tidak dapat dikirim" in payload)

    print("\nVision checks ALL PASS")


if __name__ == "__main__":
    main()
