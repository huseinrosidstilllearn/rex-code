"""
test_git_publish.py
7-scenario mock suite for git_publish() and git_status().
Covers: blocked-in-plan, empty-message, no-origin, no-changes,
        secret-detected, too-many-files, successful-push.
Uses unittest so it runs without pytest.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _make_result(returncode=0, stdout="", stderr=""):
    """Factory for subprocess.CompletedProcess-like objects."""
    r = MagicMock()
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = stderr
    return r


class TestGitStatus(unittest.TestCase):
    """Scenarios for git_status()."""

    def test_status_clean(self):
        from rex.tools import git_status
        with patch("rex.tools._run_git") as mock:
            mock.return_value = _make_result(stdout="On branch master\nnothing to commit")
            result = git_status()
            assert "nothing to commit" in result.lower() or "clean" in result.lower(), result

    def test_status_with_changes(self):
        from rex.tools import git_status
        with patch("rex.tools._run_git") as mock:
            mock.return_value = _make_result(stdout="M README.md\n?? newfile.txt")
            result = git_status()
            assert "M README" in result or "newfile" in result, result

    def test_status_git_not_found(self):
        from rex.tools import git_status
        with patch("rex.tools._run_git", side_effect=FileNotFoundError):
            result = git_status()
            assert "tidak ditemukan" in result or "not found" in result.lower(), result


class TestGitPublish(unittest.TestCase):
    """Scenarios for git_publish()."""

    def test_blocked_in_plan_mode(self):
        from rex.tools import git_publish
        with patch("rex.tools.get_active_mode", return_value="plan"):
            result = git_publish("fix bug")
            assert "PLAN" in result.upper() or "TIDAK DIIZINKAN" in result, result

    def test_empty_message_rejected(self):
        from rex.tools import git_publish
        with patch("rex.tools.get_active_mode", return_value="build"):
            for msg in ("", "   ", None):
                result = git_publish(msg)
                assert "kosong" in result or "error" in result.lower(), f"msg={msg!r}: {result}"

    def test_no_remote_origin(self):
        from rex.tools import git_publish
        with patch("rex.tools.get_active_mode", return_value="build"):
            with patch("rex.tools._run_git") as mock:
                mock.return_value = _make_result(returncode=128, stderr="fatal: not a git repository")
                result = git_publish("init")
                assert "origin" in result.lower() or "remote" in result.lower(), result

    def test_no_changes(self):
        from rex.tools import git_publish
        with patch("rex.tools.get_active_mode", return_value="build"):
            with patch("rex.tools._run_git") as mock:
                # First call: remote get-url (ok), Second: status (empty)
                mock.side_effect = [
                    _make_result(stdout="https://github.com/user/repo"),
                    _make_result(stdout=""),
                ]
                result = git_publish("wip")
                assert "tidak ada perubahan" in result.lower() or "nothing to commit" in result.lower(), result

    def test_secret_detected_in_staged_diff(self):
        from rex.tools import git_publish
        with patch("rex.tools.get_active_mode", return_value="build"):
            with patch("rex.tools._run_git") as mock:
                # Staged diff contains a GitHub token
                mock.side_effect = [
                    _make_result(stdout="https://github.com/user/repo"),  # remote
                    _make_result(stdout="M  foo.py"),                     # status
                    _make_result(stdout=""),                               # git add
                    _make_result(stdout="github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789"),  # diff
                ]
                result = git_publish("add token")
                assert "BLOKIR" in result or "blocked" in result.lower() or "secret" in result.lower(), result

    def test_too_many_files_blocked(self):
        from rex.tools import git_publish
        with patch("rex.tools.get_active_mode", return_value="build"):
            with patch("rex.tools._run_git") as mock:
                mock.side_effect = [
                    _make_result(stdout="https://github.com/user/repo"),
                    _make_result(stdout="\n".join([f"M  file{i}.py" for i in range(60)])),
                ]
                result = git_publish("bulk add")
                assert "melebihi" in result or "exceed" in result.lower() or "50" in result, result

    def test_successful_push(self):
        from rex.tools import git_publish
        with patch("rex.tools.get_active_mode", return_value="build"):
            with patch("rex.tools._run_git") as mock:
                mock.side_effect = [
                    _make_result(stdout="https://github.com/user/repo"),   # remote
                    _make_result(stdout="M  README.md"),                   # status
                    _make_result(stdout="+ new content"),                  # diff
                    _make_result(stdout=""),                               # add
                    _make_result(stdout="[main abc1234] update"),          # commit
                    _make_result(stdout=""),                              # push
                ]
                result = git_publish("update readme")
                assert "Berhasil" in result or "success" in result.lower() or "push" in result.lower(), result


if __name__ == "__main__":
    unittest.main(verbosity=2)
