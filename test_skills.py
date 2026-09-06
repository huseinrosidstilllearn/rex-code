"""Self-check skills on-demand (rex/skills.py). Run: python test_skills.py"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rex.skills import (
    format_skills_overview,
    get_skill,
    load_skills,
)


def check(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        sys.exit(1)


def make_skill(root: Path, name: str, content: str):
    directory = root / ".rex" / "skills" / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(content, encoding="utf-8")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        # ── 1. no skills dir -> empty, never raises ─────────────────────
        check("no dir -> empty", load_skills(root) == {})
        check("overview empty", format_skills_overview(root) == "")

        # ── 2. discovery + front-matter ─────────────────────────────────
        make_skill(root, "Release-Checklist", """---
name: release-checklist
description: Langkah rilis lengkap dengan checksum
---
1. bump versi
2. build
3. verify SHA256SUMS
""")
        make_skill(root, "pr-review", "# PR Review\nTinjau diff per file.\n")
        make_skill(root, "broken-folder", None if False else "")
        skills = load_skills(root)
        check("skills discovered", set(skills) == {"release-checklist", "pr-review"})
        check("front-matter name normalized", "release-checklist" in skills)
        check("front-matter description", "checksum" in skills["release-checklist"]["description"])
        check("fallback description from heading", "PR Review" in skills["pr-review"]["description"])
        check("body without front-matter", "front-matter" not in skills["release-checklist"]["body"] and "verify SHA256SUMS" in skills["release-checklist"]["body"])
        check("empty skill dropped", "broken-folder" not in skills)

        # ── 3. get_skill ────────────────────────────────────────────────
        skill = get_skill("PR-Review", workspace=root)  # case/normalize tolerant
        check("get_skill normalizes name", skill is not None and skill["name"] == "pr-review")
        check("get_skill unknown -> None", get_skill("nope", workspace=root) is None)
        check("get_skill empty -> None", get_skill("", workspace=root) is None)

        # ── 4. ordering + cap ───────────────────────────────────────────
        many = root / "many"
        for i in range(30):
            make_skill(many, f"skill-{i:02d}", f"# s{i}\nisi {i}\n")
        check("skill count capped", len(load_skills(many)) == 24)

        # ── 5. load_skill tool wiring ───────────────────────────────────
        from rex.tools import TOOL_DEFINITIONS, TOOL_REGISTRY
        check("tool registered", "load_skill" in TOOL_REGISTRY)
        check("schema defined", "load_skill" in {item["name"] for item in TOOL_DEFINITIONS})
        with patch("rex.skills.skills_dir", return_value=root / ".rex" / "skills"):
            out = TOOL_REGISTRY["load_skill"](name="release-checklist")
        check("tool loads body", "verify SHA256SUMS" in out and "Langkah rilis" in out)
        with patch("rex.skills.skills_dir", return_value=root / ".rex" / "skills"):
            missing = TOOL_REGISTRY["load_skill"](name="ghost")
        check("tool unknown -> error", "tidak ditemukan" in missing)

        # ── 6. context injection ────────────────────────────────────────
        from rex.context_inject import build_context_prefix
        original_cwd = Path.cwd()
        import os
        try:
            os.chdir(root)
            with patch("rex.context_inject.load_config", return_value={"context": {"project_memory": False, "repo_map": False, "rules": False, "skills": True, "max_context_tokens": 60000}}):
                prefix = build_context_prefix("plan")
            check("prefix lists skills", "Skills Tersedia" in prefix and "release-checklist" in prefix and "checksum" in prefix)
            with patch("rex.context_inject.load_config", return_value={"context": {"project_memory": False, "repo_map": False, "rules": False, "skills": False, "max_context_tokens": 60000}}):
                check("skills toggle off", build_context_prefix("plan") == "")
        finally:
            os.chdir(original_cwd)

        # ── 7. effective registry includes the tool ─────────────────────
        from rex.plugins import effective_tool_registry
        with patch("rex.hooks.load_hooks", return_value={"PreToolUse": [], "PostToolUse": []}):
            check("effective registry exposes load_skill", "load_skill" in effective_tool_registry())

    print("\nAll skill checks PASS")


if __name__ == "__main__":
    main()
