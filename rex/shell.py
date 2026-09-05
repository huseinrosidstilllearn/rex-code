"""
rex.shell
Cross-platform shell abstraction for the run_command sandbox.

Windows hosts execute commands through PowerShell; POSIX hosts (Linux,
macOS, and the Docker image) execute through bash. The rest of the sandbox
(blocked-command scan, allowlist, sanitized environment, workspace cwd,
output truncation) is identical on both.
"""

import os
import sys
from typing import List


def is_windows() -> bool:
    return sys.platform.startswith("win") or os.name == "nt"


def build_command_argv(command: str) -> List[str]:
    """Return the argv used to execute a sandboxed command on this platform."""
    if is_windows():
        return ["powershell", "-NoProfile", "-Command", command]
    return ["bash", "-lc", command]


def shell_name() -> str:
    return "powershell" if is_windows() else "bash"