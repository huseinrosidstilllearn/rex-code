"""Self-check autogit (AI commit/PR from real diff). Run: python test_autogit.py"""

import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rex import autogit


def check(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        sys.exit(1)


def git(cwd, *args):
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"git {args}: {result.stderr}")
    return result.stdout


def main():
    with tempfile.TemporaryDirectory() as tmp_dir:
        repo = Path(tmp_dir) / "repo"
        repo.mkdir()
        git(repo, "init", "-q")
        git(repo, "config", "user.email", "t@t.local")
        git(repo, "config", "user.name", "T")
        (repo / "a.txt").write_text("hello\n", encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "feat: initial")
        (repo / "b.txt").write_text("new file\n", encoding="utf-8")
        (repo / "a.txt").write_text("hello v2\n", encoding="utf-8")

        # ── 1. Context collection from the real diff ──────────────────────
        context = autogit.collect_git_context(cwd=repo)
        check("context sees dirty tree", context is not None)
        check("context includes branch", context and "master" in context or "main" in context)
        check("context includes new file", context and "b.txt" in context)
        check("context includes tracked diff", context and "hello v2" in context)
        check("context includes recent style", context and "feat: initial" in context)

        # Clean tree -> None (nothing to describe)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "chore: second")
        check("clean tree -> None", autogit.collect_git_context(cwd=repo) is None)

        # Diff truncation (tracked file modified -> appears in diff HEAD)
        (repo / "a.txt").write_text("x" * 30000, encoding="utf-8")
        context = autogit.collect_git_context(cwd=repo, max_chars=1000)
        check("diff truncated", context and "dipotong" in context)

    # ── 2. Subject cleaning ──────────────────────────────────────────────
    check("subject strips fences", autogit._clean_subject("```\nfeat: add x\n```") == "feat: add x")
    check("subject takes first line", autogit._clean_subject("feat: a\nextra") == "feat: a")
    check("subject capped at 72", len(autogit._clean_subject("x" * 200)) == 72)
    check("subject empty-safe", autogit._clean_subject("   \n  ") == "")

    # ── 3. commit_with_message honors confirmation ───────────────────────
    result = autogit.commit_with_message("feat: test", confirm=lambda m: False)
    check("unconfirmed -> cancelled", "DIBATALKAN" in result)
    result = autogit.commit_with_message("", confirm=lambda m: True)
    check("empty message -> cancelled", "DIBATALKAN" in result)

    # With confirmation, git_publish pipeline runs (fails on missing remote — proves it executed)
    with patch("rex.tools.git_publish") as fake_publish:
        fake_publish.return_value = "PUBLISHED"
        result = autogit.commit_with_message("feat: routed", confirm=lambda m: True)
    check("confirmed -> routed through git_publish", result == "PUBLISHED")

    # ── 4. LLM failure paths return empty strings ────────────────────────
    with patch.object(autogit, "collect_git_context", return_value=None):
        check("no context -> empty message", autogit.generate_commit_message() == "")
        check("no context -> empty pr", autogit.generate_pr_description() == "")
    with patch.object(autogit, "collect_git_context", return_value="ctx"), \
         patch.object(autogit, "_ask_llm", return_value=None):
        check("llm failure -> empty message", autogit.generate_commit_message() == "")

    # ── 5. End-to-end generate with fake LLM ─────────────────────────────
    with patch.object(autogit, "collect_git_context", return_value="Branch: master\nDiff:\nx"), \
         patch.object(autogit, "_ask_llm", return_value="fix: repair scheduler weekday mapping"):
        message = autogit.generate_commit_message()
    check("generate returns cleaned subject", message == "fix: repair scheduler weekday mapping")

    with patch.object(autogit, "collect_git_context", return_value="Branch: master\nDiff:\nx"), \
         patch.object(autogit, "_ask_llm", return_value="## Ringkasan\nAdds x.\n## Perubahan\n- a\n- b"):
        pr = autogit.generate_pr_description()
    check("pr keeps markdown structure", pr.startswith("## Ringkasan") and "## Perubahan" in pr)

    print("\nAutogit checks ALL PASS")


if __name__ == "__main__":
    main()
