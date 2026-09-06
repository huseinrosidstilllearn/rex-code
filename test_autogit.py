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

    # ── 6. Worktrees: isolated copies for parallel delegates ─────────────
    import json
    import os
    import rex.subagents as sub_mod
    from rex.subagents import run_worktree_delegates

    with tempfile.TemporaryDirectory() as repo_tmp:
        repo = Path(repo_tmp) / "proj"
        repo.mkdir()
        git(repo, "init", "-q")
        git(repo, "config", "user.email", "t@t.local")
        git(repo, "config", "user.name", "T")
        (repo / "main.py").write_text("print('v1')\n", encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "feat: init")

        check("is_git_repo detects repo", autogit.is_git_repo(repo))
        check("is_git_repo rejects non-repo", not autogit.is_git_repo(Path(repo_tmp)))

        wt = autogit.create_worktree("test-1", repo)
        check("worktree created", wt is not None and (wt / "main.py").exists())
        check("worktree branch exists", "rex-wt-test-1" in git(repo, "branch", "--list"))
        check("worktree inherits files", (wt / "main.py").read_text(encoding="utf-8") == "print('v1')\n")

        check("worktree diff empty when clean", autogit.worktree_diff("test-1", repo) == "")
        (wt / "main.py").write_text("print('v2')\n", encoding="utf-8")
        diff = autogit.worktree_diff("test-1", repo)
        check("worktree diff shows edit", "-print('v1')" in diff and "+print('v2')" in diff)
        check("main workspace untouched", (repo / "main.py").read_text(encoding="utf-8") == "print('v1')\n")

        check("worktree removed", autogit.remove_worktree("test-1", repo))
        check("worktree branch deleted", "rex-wt-test-1" not in git(repo, "branch", "--list"))
        check("remove missing is safe", not autogit.remove_worktree("test-1", repo))

        # ── 7. run_worktree_delegates (child mocked, worktrees real) ─────
        def fake_spawn(prompt, worktree, timeout):
            return 0, json.dumps({"ok": True, "response": f"analisis: {prompt[:20]}"})

        original_cwd = Path.cwd()
        try:
            os.chdir(repo)
            with patch.object(sub_mod, "_spawn_child", fake_spawn):
                results = run_worktree_delegates(
                    [{"agent": "raptor", "task": "cari bug A"}, {"agent": "trike", "task": "audit B"}],
                    timeout_sec=60,
                )
            check("delegates answered in order", [r["agent"] for r in results] == ["raptor", "trike"])
            check("delegate child output parsed", "analisis:" in results[0]["response"])
            check("delegate worktrees cleaned", not (repo / ".rex" / "worktrees").exists() or not any((repo / ".rex" / "worktrees").iterdir()))

            def failing_spawn(prompt, worktree, timeout):
                return 1, ""
            with patch.object(sub_mod, "_spawn_child", failing_spawn):
                results = run_worktree_delegates([{"agent": "dilo", "task": "x"}])
            check("child failure isolated", "Child process gagal" in results[0]["error"])

            def garbage_spawn(prompt, worktree, timeout):
                return 0, "not json"
            with patch.object(sub_mod, "_spawn_child", garbage_spawn):
                results = run_worktree_delegates([{"agent": "dilo", "task": "x"}])
            check("garbage child output noted", "tidak bisa diparse" in results[0]["error"])

            results = run_worktree_delegates([{"agent": "ghost", "task": "x"}])
            check("unknown agent rejected", "tidak dikenal" in results[0]["error"])
            results = run_worktree_delegates([{"agent": "dilo", "task": "  "}])
            check("empty task rejected", "Tugas kosong" in results[0]["error"])

            with patch("rex.subagents.request_approval", return_value=False):
                results = run_worktree_delegates([{"agent": "dilo", "task": "x"}])
            check("approval gate blocks delegates", "DITOLAK PENGGUNA" in results[0]["error"])

            check("empty tasks -> notice", "tidak ada tugas" in run_worktree_delegates([])[0]["error"])
        finally:
            os.chdir(original_cwd)

    print("\nAutogit checks ALL PASS")


if __name__ == "__main__":
    main()
