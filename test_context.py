"""Self-check for context injection (REX.md, repo map). Run: python test_context.py"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rex.context_inject as ctx
from rex.context_inject import (
    build_context_prefix,
    build_repo_map,
    create_rex_md,
    read_global_memory,
    read_project_memory,
)


def check(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        sys.exit(1)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        # ── REX.md project memory ─────────────────────────────────────
        (root / "REX.md").write_text("# Aturan\n- pakai python 3.12", encoding="utf-8")
        memory = read_project_memory(root)
        check("project memory read", "python 3.12" in memory)
        check("memory capped at 4000", len(read_project_memory(root)) <= 4100)

        # ── /init creates template ────────────────────────────────────
        fresh = root / "sub"
        fresh.mkdir()
        created, path = create_rex_md(fresh)
        check("create_rex_md creates", created and path.exists())
        check("template has rules", "REX.md" in path.read_text(encoding="utf-8"))
        created2, _ = create_rex_md(fresh)
        check("create_rex_md never overwrites", not created2)
        check("existing content intact", "REX.md" in path.read_text(encoding="utf-8"))

        # ── Repo map ──────────────────────────────────────────────────
        (root / "pkg").mkdir()
        (root / "pkg" / "a.py").write_text("x = 1", encoding="utf-8")
        (root / "pkg" / "b.py").write_text("y = 2", encoding="utf-8")
        (root / "pkg" / "__pycache__").mkdir()
        (root / "pkg" / "__pycache__" / "junk.pyc").write_text("junk", encoding="utf-8")
        (root / "requirements.txt").write_text("rich\n", encoding="utf-8")
        repo_map = build_repo_map(root)
        check("repo map shows dir with count", "pkg/" in repo_map and "2 files" in repo_map)
        check("repo map shows key file", "requirements.txt" in repo_map)
        check("repo map language stats", "py=" in repo_map)
        check("repo map skips pycache", "__pycache__" not in repo_map)
        check("repo map empty dir -> empty string", build_repo_map(root / "nonexistent") == "")

        # ── Context prefix with toggles ───────────────────────────────
        import rex.config as config_module
        original_cwd = Path.cwd()
        try:
            import os
            os.chdir(root)
            with patch_config({"context": {"project_memory": True, "repo_map": True, "max_context_tokens": 60000}}):
                prefix = build_context_prefix("plan")
                check("prefix includes project memory", "python 3.12" in prefix)
                check("prefix includes repo map", "Top-level:" in prefix)
            with patch_config({"context": {"project_memory": False, "repo_map": False, "max_context_tokens": 60000}}):
                check("toggles off -> empty prefix", build_context_prefix("plan") == "")
        finally:
            os.chdir(original_cwd)

        # ── Layered project rules (.rex/rules/) ───────────────────────
        rules_root = root / "rulesproj"
        (rules_root / ".rex" / "rules").mkdir(parents=True)
        (rules_root / "pkg").mkdir()
        (rules_root / "pkg" / ".rex" / "rules").mkdir(parents=True)
        (rules_root / ".rex" / "rules" / "zz-global.md").write_text("SELALU jalankan test dulu.", encoding="utf-8")
        (rules_root / ".rex" / "rules" / "aa-style.md").write_text("Gunakan type hints.", encoding="utf-8")
        (rules_root / "pkg" / ".rex" / "rules" / "pkg-only.md").write_text("API khusus pkg: tanpa print.", encoding="utf-8")
        (rules_root / ".rex" / "rules" / "notes.txt").write_text("bukan markdown, diabaikan", encoding="utf-8")

        pairs = ctx.collect_rules(rules_root)
        check("rules root layer first", pairs[0][0] == "seluruh proyek" and pairs[0][1] == "Gunakan type hints.")
        check("rules alphabetical in layer", pairs[1][1] == "SELALU jalankan test dulu.")
        check("rules subfolder layer", any(scope == "folder pkg/" and "tanpa print" in text for scope, text in pairs))
        check("rules ignore non-md", all("diabaikan" not in text for _, text in pairs))

        capped = root / "caprules"
        (capped / ".rex" / "rules").mkdir(parents=True)
        for i in range(15):
            (capped / ".rex" / "rules" / f"r{i:02d}.md").write_text(f"aturan {i}", encoding="utf-8")
        check("rules file cap", len(ctx.collect_rules(capped)) == ctx.MAX_RULE_FILES)

        big = root / "bigrules"
        (big / ".rex" / "rules").mkdir(parents=True)
        (big / ".rex" / "rules" / "huge.md").write_text("x" * 6000, encoding="utf-8")
        pairs_big = ctx.collect_rules(big)
        check("rules per-file cap", len(pairs_big[0][1]) <= ctx.MAX_RULE_FILE_CHARS + 30)

        none_dir = root / "norules"
        none_dir.mkdir()
        check("no rules -> empty", ctx.collect_rules(none_dir) == [])

        # Integration: rules appear in the prefix and honor the toggle
        try:
            import os
            os.chdir(rules_root)
            with patch_config({"context": {"project_memory": False, "repo_map": False, "rules": True, "max_context_tokens": 60000}}):
                prefix = build_context_prefix("plan")
                check("prefix includes rules", "Project Rules" in prefix and "jalankan test dulu" in prefix and "folder pkg/" in prefix)
            with patch_config({"context": {"project_memory": False, "repo_map": False, "rules": False, "max_context_tokens": 60000}}):
                check("rules toggle off", build_context_prefix("plan") == "")
        finally:
            os.chdir(original_cwd)

    print("\nContext checks PASS")


class patch_config:
    """Temporarily stub load_config used inside context_inject."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.original = None

    def __enter__(self):
        import rex.context_inject as module
        self.module = module
        self.original = module.load_config
        module.load_config = lambda: dict(self.cfg)
        return self

    def __exit__(self, *exc):
        self.module.load_config = self.original
        return False


if __name__ == "__main__":
    main()
