"""Self-check per-action approval in BUILD mode. Run: python test_approval.py"""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rex.approval as approval
from rex.approval import (
    DESTRUCTIVE_ACTIONS,
    request_approval,
    reset_session_allows,
    set_provider,
    summarize_action,
)
from rex.config import normalize_config
from rex.tools import delete_file, edit_file, run_command, write_file


def check(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        sys.exit(1)


SETTINGS_ON = {"enabled": True, "actions": [], "allow": {}}


def main():
    workspace = Path("workspace").resolve()
    probe = workspace / "_approval_probe.txt"
    if probe.exists():
        probe.unlink()

    # ── 1. Gate off (default): everything runs, provider never called ──
    reset_session_allows()
    set_provider(None)
    with patch.object(approval, "_get_settings", return_value={"enabled": False, "actions": [], "allow": {}}):
        check("gate off -> approved without provider", request_approval("write_file", "tulis file x.txt"))
    check("summarize write_file", summarize_action("write_file", {"path": "a.py"}) == "tulis file a.py")
    check("summarize run_command truncates", len(summarize_action("run_command", {"command": "x" * 500})) <= 140)

    # ── 2. Gate on, no provider: fail-open (additive safety) ──────────
    with patch.object(approval, "_get_settings", return_value=SETTINGS_ON):
        check("gate on + no provider -> fail open", request_approval("write_file", "tulis file x.txt"))

    # ── 3. Gate on + provider: decision respected ─────────────────────
    answers = {"value": False}
    def fake_provider(action, summary):
        return answers["value"]
    set_provider(fake_provider)
    with patch.object(approval, "_get_settings", return_value=SETTINGS_ON):
        answers["value"] = True
        check("provider approves", request_approval("run_command", "jalankan perintah: dir"))
        answers["value"] = False
        check("provider denies", not request_approval("run_command", "jalankan perintah: dir"))

        # ── 4. Action filter: only gated actions prompt ───────────────
        calls = []
        def counting_provider(action, summary):
            calls.append(action)
            return True
        set_provider(counting_provider)
        with patch.object(approval, "_get_settings", return_value={**SETTINGS_ON, "actions": ["run_command"]}):
            request_approval("write_file", "tulis file x.txt")
            check("non-gated action skips provider", calls == [])
            request_approval("run_command", "jalankan perintah: dir")
            check("gated action hits provider", calls == ["run_command"])

        # ── 5. Config-level allow globs ───────────────────────────────
        settings_allow = {"enabled": True, "actions": [], "allow": {"run_command": ["jalankan perintah: pip *"]}}
        with patch.object(approval, "_get_settings", return_value=settings_allow):
            check("config allow glob matches", request_approval("run_command", "Jalankan perintah: pip install flask"))
            check("config allow glob non-match prompts", request_approval("run_command", "jalankan perintah: del /q semua"))
            check("provider consulted exactly once for non-match", calls == ["run_command", "run_command"])

        # ── 6. Session-level 'always' from (True, pattern) tuples ─────
        reset_session_allows()
        def tuple_provider(action, summary):
            calls.append(action)
            return (True, "jalankan perintah: git *")
        set_provider(tuple_provider)
        with patch.object(approval, "_get_settings", return_value=SETTINGS_ON):
            calls.clear()
            check("first ask returns True", request_approval("run_command", "jalankan perintah: git status"))
            check("first ask consulted provider", calls == ["run_command"])
            check("same-pattern ask skips provider", request_approval("run_command", "jalankan perintah: git push origin"))
            check("provider not re-called after always", calls == ["run_command"])
            reset_session_allows()
            request_approval("run_command", "jalankan perintah: git status")
            check("reset clears session allows", calls == ["run_command", "run_command"])
    set_provider(None)

    # ── 7. Real tools honor denial (BUILD mode + gate on + deny) ──────
    def denying_provider(action, summary):
        return False
    set_provider(denying_provider)
    tools_gate = {"enabled": True, "actions": [], "allow": {}}
    with patch("rex.tools.get_active_mode", return_value="build"), \
         patch("rex.tools.request_approval", side_effect=request_approval), \
         patch("rex.tools.load_config", return_value={}), \
         patch.object(approval, "_get_settings", return_value=tools_gate):
        result = write_file(str(probe.relative_to(workspace)), "halo")
        check("write_file denied -> no file written", not probe.exists() and "DITOLAK" in result)
        probe.write_text("isi", encoding="utf-8")
        result = edit_file(str(probe.relative_to(workspace)), "isi", "ganti")
        check("edit_file denied -> content unchanged", probe.read_text(encoding="utf-8") == "isi" and "DITOLAK" in result)
        result = delete_file(str(probe.relative_to(workspace)))
        check("delete_file denied -> file intact", probe.exists() and "DITOLAK" in result)
        result = run_command("echo halo")
        check("run_command denied -> not executed", "DITOLAK" in result)
    set_provider(None)

    # ── 8. Real tools proceed on approval ─────────────────────────────
    def approving_provider(action, summary):
        return True
    set_provider(approving_provider)
    with patch("rex.tools.get_active_mode", return_value="build"), \
         patch("rex.tools.request_approval", side_effect=request_approval), \
         patch("rex.tools.load_config", return_value={}), \
         patch.object(approval, "_get_settings", return_value=tools_gate):
        result = write_file(str(probe.relative_to(workspace)), "halo")
        check("write_file approved -> written", probe.exists() and "Berhasil" in result)
        result = delete_file(str(probe.relative_to(workspace)))
        check("delete_file approved -> deleted", not probe.exists() and "Berhasil" in result)
        result = run_command("echo halo-approval")
        check("run_command approved -> executed", "halo-approval" in result)
    set_provider(None)
    reset_session_allows()

    # ── 9. Config normalization ───────────────────────────────────────
    cfg = normalize_config({"approval": {"enabled": "yes", "actions": [" run_command ", "bogus", 5], "allow": {"run_command": "jalankan perintah: pip *"}}})
    appr = cfg["approval"]
    check("enabled coerced to bool", appr["enabled"] is True)
    check("actions cleaned & sorted", appr["actions"] == ["bogus", "run_command"])
    check("allow values normalized to str list", appr["allow"]["run_command"] == ["jalankan perintah: pip *"])
    cfg2 = normalize_config({})
    check("defaults: approval off", cfg2["approval"]["enabled"] is False and cfg2["approval"]["actions"] == [])

    # ── 10. All destructive actions (incl. external tools) are gated ──
    check("destructive set complete", set(DESTRUCTIVE_ACTIONS) == {"write_file", "edit_file", "delete_file", "run_command", "git_publish", "mcp_tool", "plugin_tool"})

    print("\nApproval checks PASS")


if __name__ == "__main__":
    main()
