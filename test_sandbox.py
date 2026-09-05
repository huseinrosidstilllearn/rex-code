"""Self-check command guardrails. Run: python test_sandbox.py"""
import os
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

from rex.tools import run_command


def check(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    if not condition:
        raise AssertionError(name)


def run_build(command, config=None):
    cfg = {
        "terminal_timeout_sec": 7,
        "terminal_output_max_chars": 80,
        "command_allowlist": ["python", "pip", "dir"],
        **(config or {}),
    }
    completed = SimpleNamespace(stdout="ok", stderr="", returncode=0)
    with patch("rex.tools.get_active_mode", return_value="build"), \
         patch("rex.tools.load_config", return_value=cfg), \
         patch("rex.tools.subprocess.run", return_value=completed) as process:
        result = run_command(command)
    return result, process


# Plan mode remains read-only.
with patch("rex.tools.get_active_mode", return_value="plan"), \
     patch("rex.tools.subprocess.run") as process:
    result = run_command("python --version")
check("plan mode blocks execution", "TIDAK DIIZINKAN" in result and not process.called)

# High-risk command families never reach subprocess.
blocked = [
    r"Remove-Item -Recurse -Force C:\Users",
    r"del ..\secret.txt",
    "iex('Get-Process')",
    "Invoke-Expression $payload",
    "Stop-Computer",
    "Restart-Computer",
    "Set-ExecutionPolicy Bypass",
    "Format-Volume -DriveLetter C",
    "reg delete HKCU\\Software\\Demo /f",
    "net user attacker password /add",
    "Get-Content ../.env",
    "Get-Content .env",
    r"Get-Content C:\Windows\win.ini",
    "echo $env:GEMINI_API_KEY",
]
for command in blocked:
    result, process = run_build(command)
    check(f"blocked: {command}", "DIBLOKIR" in result and not process.called)

# Safe command executes with configured cwd, timeout, and sanitized environment.
with patch.dict(os.environ, {
    "VISIBLE_SETTING": "yes",
    "GEMINI_API_KEY": "secret",
    "SERVICE_TOKEN": "secret",
    "DB_PASSWORD": "secret",
}, clear=False):
    result, process = run_build("python --version")
kwargs = process.call_args.kwargs
check("safe command executes", process.call_count == 1 and "ok" in result)
check("configured timeout used", kwargs["timeout"] == 7)
check("workspace cwd used", kwargs["cwd"].name == "workspace")
check("API key removed from child env", "GEMINI_API_KEY" not in kwargs["env"])
check("token removed from child env", "SERVICE_TOKEN" not in kwargs["env"])
check("password removed from child env", "DB_PASSWORD" not in kwargs["env"])
check("normal env retained", kwargs["env"]["VISIBLE_SETTING"] == "yes")

# Output is capped before returning to model.
completed = SimpleNamespace(stdout="x" * 200, stderr="", returncode=0)
with patch("rex.tools.get_active_mode", return_value="build"), \
     patch("rex.tools.load_config", return_value={
         "terminal_timeout_sec": 7,
         "terminal_output_max_chars": 80,
         "command_allowlist": ["python"],
     }), \
     patch("rex.tools.subprocess.run", return_value=completed):
    result = run_command("python noisy.py")
check("large output truncated", len(result) <= 120 and "dipotong" in result.lower())

# Timeout reports configured duration.
with patch("rex.tools.get_active_mode", return_value="build"), \
     patch("rex.tools.load_config", return_value={"terminal_timeout_sec": 7}), \
     patch("rex.tools.subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 7)):
    result = run_command("python slow.py")
check("configured timeout reported", "7 detik" in result)

print("\nAll command guardrail checks passed.")