"""Self-check for the auto-update engine. Run: python test_updates.py"""

import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rex
import rex.updates as updates
from rex.updates import (
    check_for_update,
    compare_versions,
    download_asset,
    install_update,
    maybe_update,
    pick_asset,
    verify_checksum,
)
from rex.config import normalize_config


def check(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        sys.exit(1)


def fake_response(status_code=200, payload=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload if payload is not None else {}
    return resp


def fake_stream(chunks=(b"x" * 2_000_000,), status_code=200):
    """Build a mock for httpx.stream(...) usable as a context manager."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.iter_bytes.return_value = iter(chunks)
    ctx = MagicMock()
    ctx.__enter__.return_value = resp
    ctx.__exit__.return_value = False
    return ctx


RELEASE_NEWER = {"tag_name": "v0.4.0", "assets": []}
SETTINGS = {
    "enabled": True,
    "repo": "acme/rex-code",
    "timeout_sec": 5,
    "check_interval_hours": 24,
    "auto_download": False,
    "auto_install": False,
    "download_dir": None,
}


def main():
    tmp = Path(tempfile.mkdtemp())
    cache_file = tmp / "last_update_check.json"

    # ── 1. Version comparison ────────────────────────────────────────
    check("0.1.0 == 0.1.0", compare_versions("0.1.0", "0.1.0") == 0)
    check("0.2.0 > 0.1.0", compare_versions("0.2.0", "0.1.0") == 1)
    check("0.1.0 < 0.2.0", compare_versions("0.1.0", "0.2.0") == -1)
    check("0.1.1 > 0.1.0", compare_versions("0.1.1", "0.1.0") == 1)
    check("1.0 == 1.0.0 (missing segments)", compare_versions("1.0", "1.0.0") == 0)
    check("v0.2.0 > 0.1.0 (prefix v)", compare_versions("v0.2.0", "0.1.0") == 1)
    check("0.1.0-beta == 0.1.0 (suffix)", compare_versions("0.1.0-beta", "0.1.0") == 0)
    check("0.10.0 > 0.9.0 (numeric, not lexical)", compare_versions("0.10.0", "0.9.0") == 1)
    check("current __version__ is 0.3.0", rex.__version__ == "0.3.0")

    # ── 2. GitHub release fetch (mocked, never raises) ───────────────
    with patch.object(updates.httpx, "get", return_value=fake_response(200, RELEASE_NEWER)):
        check("release fetched on 200", updates.get_latest_release("acme/rex-code") == RELEASE_NEWER)
    with patch.object(updates.httpx, "get", return_value=fake_response(404)):
        check("404 -> None", updates.get_latest_release("acme/rex-code") is None)
    with patch.object(updates.httpx, "get", side_effect=ConnectionError("offline")):
        check("network error -> None (no raise)", updates.get_latest_release("acme/rex-code") is None)

    # ── 3. Asset picking per platform ────────────────────────────────
    good_exe = {"name": "RexCode-Setup-v0.2.0-x64.exe", "size": 27_000_000,
                "browser_download_url": "https://github.com/acme/rex-code/releases/download/v0.2.0/RexCode-Setup-v0.2.0-x64.exe"}
    linux_zip = {"name": "rex-linux-x64.zip", "size": 20_000_000,
                 "browser_download_url": "https://github.com/acme/rex-code/releases/download/v0.2.0/rex-linux-x64.zip"}
    macos_zip = {"name": "rex-macos-arm64.zip", "size": 20_000_000,
                 "browser_download_url": "https://github.com/acme/rex-code/releases/download/v0.2.0/rex-macos-arm64.zip"}
    check("windows asset picked", pick_asset([good_exe, linux_zip], "Windows") == good_exe)
    check("linux asset picked", pick_asset([good_exe, linux_zip], "Linux") == linux_zip)
    check("macos asset picked", pick_asset([good_exe, macos_zip], "Darwin") == macos_zip)
    check("no match -> None", pick_asset([{"name": "readme.txt", "size": 10,
                                           "browser_download_url": "https://github.com/x/r.txt"}], "Windows") is None)
    tiny = dict(good_exe, size=100)
    check("tiny asset rejected", pick_asset([tiny], "Windows") is None)
    http_url = dict(good_exe, browser_download_url="http://evil.example.com/RexCode-Setup-v0.2.0-x64.exe")
    check("non-https asset rejected", pick_asset([http_url], "Windows") is None)

    # ── 4. Download (mocked stream, atomic, keeps one installer) ────
    dest = tmp / "downloads"
    url = good_exe["browser_download_url"]
    old = dest / "RexCode-Setup-v0.1.0-x64.exe"
    dest.mkdir(parents=True)
    old.write_bytes(b"old installer")
    with patch.object(updates.httpx, "stream", return_value=fake_stream()):
        result = download_asset(url, dest)
    check("download succeeded", result == dest / "RexCode-Setup-v0.2.0-x64.exe")
    check("downloaded file has content", result.is_file() and result.stat().st_size >= 1_000_000)
    check("old installer removed (keep one)", not old.exists())
    check("no .part leftover", not (dest / "RexCode-Setup-v0.2.0-x64.exe.part").exists())

    with patch.object(updates.httpx, "stream", side_effect=ConnectionError("boom")):
        check("download failure -> None", download_asset(url, dest) is None)
    check("failed download leaves no .part", not any(p.name.endswith(".part") for p in dest.iterdir()))
    with patch.object(updates.httpx, "stream") as mock_stream:
        check("disallowed filename never hits network", download_asset("https://github.com/x/evil.exe", dest) is None)
        mock_stream.assert_not_called()

    # ── 4b. verify_checksum: basename tolerance + edge cases ─────────
    installer = dest / "RexCode-Setup-v0.2.0-x64.exe"
    setup_file = tmp / "SHA256SUMS.txt"
    real_digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    setup_file.write_text(
        f"{real_digest}  windows-installer/{installer.name}\n"
        f"{'0' * 64}  rex-linux-x64.zip\n",
        encoding="utf-8",
    )
    check("verify: path prefix in entry still matches (regression v0.2.0)",
          verify_checksum(installer, setup_file) is True)
    setup_file.write_text(f"{real_digest}  {installer.name}\n", encoding="utf-8")
    check("verify: plain name still matches", verify_checksum(installer, setup_file) is True)
    setup_file.write_text(f"{'0' * 64}  windows-installer/{installer.name}\n", encoding="utf-8")
    check("verify: prefix + wrong hash -> False", verify_checksum(installer, setup_file) is False)
    setup_file.write_text(f"{real_digest}  other-file.exe\n", encoding="utf-8")
    check("verify: no entry -> None (fail-safe)", verify_checksum(installer, setup_file) is None)
    check("verify: missing checksums file -> None", verify_checksum(installer, tmp / "nope.txt") is None)

    # ── 5. check_for_update: cache + flags ───────────────────────────
    with patch.object(updates, "CACHE_FILE", cache_file):
        cache_file.write_text("{}", encoding="utf-8")
        with patch.object(updates.httpx, "get", return_value=fake_response(200, RELEASE_NEWER)):
            got = check_for_update(SETTINGS)
        check("newer version detected", got == "0.4.0")
        check("cache written after check", json.loads(cache_file.read_text())["newer_version"] == "0.4.0")

        # fresh cache: zero network calls
        with patch.object(updates.httpx, "get", side_effect=AssertionError("network called")) as m:
            check("fresh cache serves 0.4.0", check_for_update(SETTINGS) == "0.4.0")
            m.assert_not_called()
        cache_file.write_text(json.dumps({"checked_at": time.time(), "latest": "v0.1.0", "newer_version": ""}), encoding="utf-8")
        with patch.object(updates.httpx, "get", side_effect=AssertionError("network called")) as m:
            check("fresh cache, up-to-date -> None", check_for_update(SETTINGS) is None)
            m.assert_not_called()

        # stale cache triggers a new network call
        cache_file.write_text(json.dumps({"checked_at": time.time() - 25 * 3600, "latest": "v0.1.0", "newer_version": ""}), encoding="utf-8")
        with patch.object(updates.httpx, "get", return_value=fake_response(200, RELEASE_NEWER)) as m:
            check("stale cache re-checks network", check_for_update(SETTINGS) == "0.4.0")
            m.assert_called_once()

        # network failure with stale cache -> None, failure cached (no raise)
        cache_file.write_text(json.dumps({"checked_at": time.time() - 25 * 3600}), encoding="utf-8")
        with patch.object(updates.httpx, "get", side_effect=ConnectionError("down")):
            check("network failure -> None", check_for_update(SETTINGS) is None)
        check("failure cached to avoid hammering", "checked_at" in json.loads(cache_file.read_text()))

        # disabled: zero network
        with patch.object(updates.httpx, "get", side_effect=AssertionError("network called")) as m:
            check("disabled -> None", check_for_update({**SETTINGS, "enabled": False}) is None)
            m.assert_not_called()

    # ── 6. maybe_update: full flow, checksum gate, anti-loop, flags ──
    with patch.object(updates, "CACHE_FILE", cache_file):
        notices = []
        installed = []
        cache_file.write_text("{}", encoding="utf-8")
        with patch.object(updates, "check_for_update", return_value="0.2.0"), \
             patch.object(updates, "get_latest_release", return_value={**RELEASE_NEWER, "assets": [good_exe]}), \
             patch.object(updates, "download_asset", return_value=dest / "RexCode-Setup-v0.2.0-x64.exe"), \
             patch.object(updates, "download_checksums", return_value=tmp / "SHA256SUMS.txt"), \
             patch.object(updates, "verify_checksum", return_value=True):
            maybe_update({**SETTINGS, "auto_download": True, "auto_install": True,
                          "download_dir": str(dest)}, notices.append, installed.append)
        check("notice emitted", any("0.2.0" in n for n in notices))
        check("installer handed to install hook (checksum verified)", len(installed) == 1)
        check("anti-loop marker stored", json.loads(cache_file.read_text())["installed_version"] == "0.2.0")

        # checksum mismatch: installer discarded, never executed
        notices_bad, installed_bad = [], []
        with patch.object(updates, "check_for_update", return_value="0.2.0"), \
             patch.object(updates, "get_latest_release", return_value={**RELEASE_NEWER, "assets": [good_exe]}), \
             patch.object(updates, "download_asset", return_value=dest / "RexCode-Setup-v0.2.0-x64.exe"), \
             patch.object(updates, "download_checksums", return_value=tmp / "SHA256SUMS.txt"), \
             patch.object(updates, "verify_checksum", return_value=False):
            maybe_update({**SETTINGS, "auto_download": True, "auto_install": True,
                          "download_dir": str(dest)}, notices_bad.append, installed_bad.append)
        check("checksum mismatch -> no install", len(installed_bad) == 0)
        check("checksum mismatch -> installer discarded", not (dest / "RexCode-Setup-v0.2.0-x64.exe").exists())
        check("checksum mismatch -> warning notice", any("checksum" in n.lower() for n in notices_bad))

        # release without SHA256SUMS.txt: fail-safe, never auto-executes
        notices_nos, installed_nos = [], []
        with patch.object(updates, "check_for_update", return_value="0.2.0"), \
             patch.object(updates, "get_latest_release", return_value={**RELEASE_NEWER, "assets": [good_exe]}), \
             patch.object(updates, "download_asset", return_value=dest / "RexCode-Setup-v0.2.0-x64.exe"), \
             patch.object(updates, "download_checksums", return_value=None):
            maybe_update({**SETTINGS, "auto_download": True, "auto_install": True,
                          "download_dir": str(dest)}, notices_nos.append, installed_nos.append)
        check("no checksums -> no install (fail-safe)", len(installed_nos) == 0)

        # anti-loop: same version again -> no second install
        notices2, installed2 = [], []
        with patch.object(updates, "check_for_update", return_value="0.2.0"), \
             patch.object(updates, "get_latest_release", return_value={**RELEASE_NEWER, "assets": [good_exe]}), \
             patch.object(updates, "download_asset", return_value=dest / "RexCode-Setup-v0.2.0-x64.exe"), \
             patch.object(updates, "download_checksums", return_value=tmp / "SHA256SUMS.txt"), \
             patch.object(updates, "verify_checksum", return_value=True):
            maybe_update({**SETTINGS, "auto_download": True, "auto_install": True,
                          "download_dir": str(dest)}, notices2.append, installed2.append)
        check("no re-install for same version", len(installed2) == 0)

        # auto_install off -> notice only, no install
        cache_file.write_text("{}", encoding="utf-8")
        notices3, installed3 = [], []
        with patch.object(updates, "check_for_update", return_value="0.2.0"), \
             patch.object(updates, "get_latest_release", return_value={**RELEASE_NEWER, "assets": [good_exe]}), \
             patch.object(updates, "download_asset", return_value=dest / "RexCode-Setup-v0.2.0-x64.exe"), \
             patch.object(updates, "download_checksums", return_value=tmp / "SHA256SUMS.txt"), \
             patch.object(updates, "verify_checksum", return_value=True):
            maybe_update({**SETTINGS, "auto_download": True, "auto_install": False,
                          "download_dir": str(dest)}, notices3.append, installed3.append)
        check("auto_install=false -> no install", len(installed3) == 0)

        # auto_download off -> manual link notice, no download
        cache_file.write_text("{}", encoding="utf-8")
        notices4, installed4 = [], []
        with patch.object(updates, "check_for_update", return_value="0.2.0"), \
             patch.object(updates, "download_asset", side_effect=AssertionError("download called")):
            maybe_update({**SETTINGS, "auto_download": False}, notices4.append, installed4.append)
        check("manual link shown", any("releases/latest" in n for n in notices4))
        check("no download when auto_download=false", len(installed4) == 0)

        # disabled -> totally silent
        notices5, installed5 = [], []
        maybe_update({**SETTINGS, "enabled": False}, notices5.append, installed5.append)
        check("disabled -> silent", not notices5 and not installed5)

        # up-to-date -> silent
        notices6, installed6 = [], []
        with patch.object(updates, "check_for_update", return_value=None):
            maybe_update(SETTINGS, notices6.append, installed6.append)
        check("up-to-date -> silent", not notices6 and not installed6)

    # ── 7. install_update guards ─────────────────────────────────────
    check("missing installer -> False", install_update(tmp / "nope-does-not-exist.exe") is False)

    # ── 8. Config normalization for the updates section ──────────────
    cfg = normalize_config({"updates": {"repo": "not-a-repo", "timeout_sec": 999, "auto_install": "yes"}})
    u = cfg["updates"]
    check("invalid repo repaired", u["repo"] == SETTINGS["repo"] if False else u["repo"].count("/") == 1)
    check("timeout clamped", u["timeout_sec"] <= 30)
    check("auto_install coerced to bool", u["auto_install"] is True)
    check("defaults filled (enabled)", u["enabled"] is True)

    # ── 9. Version centralization across the repo ────────────────────
    iss = Path("installer/windows/rexcode.iss").read_text(encoding="utf-8")
    check("installer default version 0.3.0", '#define AppVersion "0.3.0"' in iss)
    tui = Path("rex/tui/app.py").read_text(encoding="utf-8")
    check("TUI banner uses __version__ (no hardcoded 1.0.0)", 'Rex Code v{rex.__version__}' in tui and "v1.0.0" not in tui)
    cli_src = Path("cli.py").read_text(encoding="utf-8")
    check("CLI banner uses __version__ (no hardcoded 1.0.0)", "{__version__}" in cli_src and "v1.0.0" not in cli_src)

    print("\nUpdate checks PASS")


if __name__ == "__main__":
    main()
