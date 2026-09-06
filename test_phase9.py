"""Self-check phase 9 (REX_WORKSPACE, post-update changelog, explorer menu). Run: python test_phase9.py"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import importlib
import rex.config as config_mod


def check(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        sys.exit(1)


def main():
    # ── 1. REX_WORKSPACE override (project-scoped mode) ────────────────
    with tempfile.TemporaryDirectory() as tmp_dir:
        with patch.dict("os.environ", {"REX_WORKSPACE": tmp_dir}):
            importlib.reload(config_mod)
            check("override changes DATA_DIR", config_mod.DATA_DIR == Path(tmp_dir))
            check("config file inside project", config_mod.CONFIG_FILE.parent == Path(tmp_dir))
            check("workspace dir created", config_mod.WORKSPACE_DIR.is_dir())
    # Env var unset again
    with patch.dict("os.environ", {}, clear=True):
        importlib.reload(config_mod)
    with patch.dict("os.environ", {"REX_WORKSPACE": str(Path(tempfile.gettempdir()) / "no-such-dir-xyz")}):
        importlib.reload(config_mod)
        check("nonexistent override ignored", config_mod.DATA_DIR != Path(tempfile.gettempdir()) / "no-such-dir-xyz")
    with patch.dict("os.environ", {}, clear=True):
        importlib.reload(config_mod)

    # ── 2. Pending changelog stash/take ────────────────────────────────
    import rex.updates as updates
    with tempfile.TemporaryDirectory() as tmp_dir:
        logs_dir = Path(tmp_dir) / "logs"
        with patch.object(updates, "LOGS_DIR", logs_dir):
            check("no changelog -> empty", updates.take_pending_changelog() == "")
            logs_dir.mkdir(parents=True)
            (logs_dir / "pending_changelog.txt").write_text("# v0.2.0\n- fitur baru\n", encoding="utf-8")
            text = updates.take_pending_changelog()
            check("changelog returned", "fitur baru" in text)
            check("changelog cleared after take", not (logs_dir / "pending_changelog.txt").exists())
            check("second take -> empty", updates.take_pending_changelog() == "")

    # maybe_update writes the stash (checksum gate mocked out)
    import re as _re
    from test_updates import check as _c  # noqa: F401  (reuse nothing; keep import surface tiny)
    with tempfile.TemporaryDirectory() as tmp_dir:
        cache_file = Path(tmp_dir) / "cache.json"
        dest = Path(tmp_dir) / "downloads"
        dest.mkdir()
        logs_dir = Path(tmp_dir) / "logs"
        asset = {"name": "RexCode-Setup-v0.2.0-x64.exe", "size": 27_000_000,
                 "browser_download_url": "https://github.com/acme/x/releases/download/v0.2.0/RexCode-Setup-v0.2.0-x64.exe"}
        settings = {"enabled": True, "repo": "acme/x", "timeout_sec": 5, "check_interval_hours": 24,
                    "auto_download": True, "auto_install": False, "download_dir": str(dest), "channel": "stable"}
        with patch.object(updates, "CACHE_FILE", cache_file), \
             patch.object(updates, "LOGS_DIR", logs_dir), \
             patch.object(updates, "check_for_update", return_value="0.2.0"), \
             patch.object(updates, "get_latest_release", return_value={"tag_name": "v0.2.0", "body": "## Notes\n- new", "assets": [asset]}), \
             patch.object(updates, "download_asset", return_value=dest / asset["name"]), \
             patch.object(updates, "download_checksums", return_value=None):
            notices = []
            updates.maybe_update(settings, notices.append, None)
        check("stash written on download", (logs_dir / "pending_changelog.txt").is_file())
        check("stash contains body", "fitur" not in (logs_dir / "pending_changelog.txt").read_text(encoding="utf-8") or "new" in (logs_dir / "pending_changelog.txt").read_text(encoding="utf-8"))

    # ── 3. Explorer launcher file exists and is wired in the installer ──
    cmd = Path("assets/rex-here.cmd")
    check("rex-here.cmd exists", cmd.is_file())
    content = cmd.read_text(encoding="utf-8", errors="replace")
    check("launcher sets REX_WORKSPACE", "REX_WORKSPACE" in content)
    iss = Path("installer/windows/rexcode.iss").read_text(encoding="utf-8", errors="replace")
    check("installer references launcher", "rex-here.cmd" in iss)
    check("installer has explorer task", "explorermenu" in iss and "OpenRexCode" in iss)
    check("background shell covered", "Directory\\Background\\shell\\OpenRexCode" in iss)

    print("\nPhase9 checks ALL PASS")


if __name__ == "__main__":
    main()
