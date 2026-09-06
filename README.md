<div align="center">

![Rex Code Banner](docs/brand/banner.png)

# 🦖 Rex Code

**Autonomous AI Coding Agent — Native Windows App**

You think it, Rex builds it. PLAN before you act, BUILD when you approve —
with a sandboxed tool layer, sub-agent specialists, and one-click installer.

[![Release](https://img.shields.io/badge/Release-v0.1.0-22C55E?logo=github)](https://github.com/huseinrosidstilllearn/rex-code/releases/latest)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](#-from-source)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-0078D4?logo=windows)](#-from-source)
[![License](https://img.shields.io/badge/License-MIT-8B5CF6)](LICENSE)

**[⬇️ Download Installer](https://github.com/huseinrosidstilllearn/rex-code/releases/latest)** · [Panduan Bahasa Indonesia](PANDUAN-INSTALL.md)

</div>

---

## 🚀 Quick Install (Windows)

1. Download **`RexCode-Setup-v0.1.0-x64.exe`** from [Releases](https://github.com/huseinrosidstilllearn/rex-code/releases/latest).
2. Run it — if SmartScreen appears: **More info → Run anyway** (normal for unsigned open-source apps; see [guide](PANDUAN-INSTALL.md)).
3. Follow the wizard (EN/🇮🇩), then launch **Rex Code** from the Start Menu.
4. First run: put `GEMINI_API_KEY=...` in `%LOCALAPPDATA%\RexCode\.env` ([free key](https://aistudio.google.com)) — Rex shows you exactly where when it starts.

All user data lives in `%LOCALAPPDATA%\RexCode\` (config, sessions, logs, downloads) — never inside the install folder. Updates are checked once a day and installed automatically; every step can be switched off in `config.json → updates`.

---

## ✨ What Rex Code Can Do

| | |
| --- | --- |
| **🧠 Plan / Build modes** | PLAN researches read-only; BUILD writes code, runs commands, auto-debugs. One keypress to switch. |
| **🔁 ReAct loop with self-healing** | Tool results feed the next thought; terminal errors trigger automatic fixes and re-runs. |
| **🔌 Multi-provider** | Google Gemini, 9router, OmniRoute/OpenRouter, any OpenAI-compatible API, local Ollama — switch without restarting. |
| **🦕 Sub-agent specialists** | Five read-only dinosaur analysts — Brachio (review), Raptor (bugs), Trike (security), Ptero (architecture), Dilo (quality). |
| **🎙️ Voice input** | `/voice` — speak your instruction, Whisper transcribes it (Gemini/OpenAI/offline engines). |
| **🧩 Plugin system** | Drop a `.py` file in `plugins/`, get a new agent tool for every provider. Broken plugins never crash the agent. |
| **⏰ Scheduler** | Cron-style jobs — nightly reviews, auto-commits (`/scheduler`). |
| **🔒 Security rails** | Path traversal, sensitive files, dangerous commands, and secret leaks are blocked by default. |
| **🎨 Native TUI** | Claude-Code-style terminal app with 7 themes, streaming, markdown, command palette (Ctrl+P). |
| **📦 Installer + auto-update** | Real EXE installer (Inno Setup) with daily self-update from GitHub Releases. |
| **🧹 Anti-slop guardrail** | Strips AI clichés (`leverage`, `tapestry`, `game changer`) from output. |
| **💾 Local sessions** | History survives restarts; secrets are redacted before persistence. |

---

## 🛠️ From Source

```powershell
git clone https://github.com/huseinrosidstilllearn/rex-code.git
cd rex-code
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env        # fill GEMINI_API_KEY
start_cli.bat                 # or: python cli.py
```

Native TUI: `python rex/tui/cli_entry.py` · Classic CLI: `python cli.py`

---

## ⌨️ Commands

| Command | Effect |
| --- | --- |
| `/plan` `/build` | Switch mode (read-only ↔ autonomous). |
| `/models` | Pick provider + model interactively. |
| `/settings` | Toggle anti-slop, streaming, voice, max steps, update flags. |
| `/voice` | Voice input → Whisper transcription. |
| `/n8n` | Generate webhook-AI workflow JSON for n8n/Activepieces. |
| `/scheduler` | View cron jobs, trigger manually. |
| `/anti-slop` | Audit & clean AI clichés in your text. |
| `/files` | List workspace files. |
| `/sessions` `/new` `/use <id>` `/delete <id>` | Session management. |
| `/help` `/exit` | You guessed it. |

The TUI adds a **Ctrl+P command palette** and `/theme` (rex, mono, amber, cyan, violet, rose, custom `#RRGGBB`).

---

## 🧰 Agent Tools

| Tool | Mode | Purpose |
| --- | --- | --- |
| `read_file` `list_dir` `search_files` `search_content` | PLAN & BUILD | Read and explore the workspace. |
| `write_file` `edit_file` `delete_file` | BUILD only | Create and modify files. |
| `run_command` | BUILD only | Sandboxed shell (PowerShell / bash). |
| `git_status` `git_publish` | BUILD for publish | Stage → secret-scan → commit → push. |
| `delegate_to_brachio` / `raptor` / `trike` / `ptero` / `dilo` | PLAN only | Sub-agent specialists (read-only). |

Plugins extend this list automatically — see [`plugins/current_time.py`](plugins/current_time.py) as the template.

In BUILD mode, the five destructive tools (`write_file`, `edit_file`, `delete_file`, `run_command`, `git_publish`) can require per-action confirmation — enable it in `/settings` → `approval`, or in `config.json`. Answer **always** to store a session allowlist pattern (e.g. `git status` style commands stop prompting).

---

## 🔄 Auto-Update

Rex checks GitHub Releases **at most once per day**, downloads the new installer to
`%LOCALAPPDATA%\RexCode\downloads\`, launches it (Windows UAC + Inno wizard), and exits
cleanly so the binary can replace itself. Anti-loop: at most one install attempt per
version, so cancelling the wizard never spawns endless relaunches. Offline / no release /
rate-limited → silent skip, never blocks startup.

| Key (`config.json → updates`) | Default | Meaning |
| --- | --- | --- |
| `enabled` | `true` | Check for updates |
| `auto_download` | `true` | Download installer automatically |
| `auto_install` | `true` | Run installer after download |
| `check_interval_hours` | `24` | Minimum interval between checks |

---

## 🧩 Plugin System

```python
# plugins/my_tool.py
PLUGIN_TOOLS = [{
    "name": "my_tool",
    "description": "What it does for the LLM.",
    "parameters": {"type": "object", "properties": {}, "required": []},
    "handler": my_handler,   # callable; kwargs match parameters
}]
```

Single file or a package with `plugin.py`. Gate by `config.json → plugins`
(`enabled`, `list` allowlist). Merged into the tool schema for **both** the Gemini
provider and OpenAI-compatible routers.

---

## 🔔 Webhook / CI Review (engine ready)

`rex/webhooks.py` verifies GitHub HMAC signatures, filters PR/comment events, builds PR
context, runs a review, and posts the 🦖 comment back — fully tested (22 checks). The
HTTP host for it is on the [roadmap](#%EF%B8%8F-roadmap) alongside headless mode.

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────┐
│  Native TUI (rex/tui)        Classic CLI (cli.py)        │
│            ↘                    ↙                         │
│      RexAgent.run() — ReAct loop + StepEvent callbacks   │
│            ↓                                              │
│  Tools (rex/tools.py) + Plugins (rex/plugins.py)         │
│  ├── file ops, search, sandboxed shell (rex/shell.py)    │
│  ├── git_status / git_publish (secret-scan guarded)      │
│  └── sub-agents (rex/subagents.py)                       │
│            ↓                                              │
│  Provider router (rex/providers/)                        │
│  Gemini · 9router · OmniRoute · OpenAI-compatible · Ollama│
│            ↓                                              │
│  Anti-slop filter · Sessions · Scheduler · Auto-update   │
└──────────────────────────────────────────────────────────┘
```

**Key invariants** — mode gate on every write/run tool · path sandbox blocks `..` and
sensitive files · secrets redacted before persistence · cooperative abort between steps.

---

## 🛡️ Security by Default

| Threat | Defense |
| --- | --- |
| Path traversal (`../secrets`) | `resolve_path` + `is_relative_to` |
| Editing `.env` / `*.pem` / `*.key` | sensitive-file blocklist |
| `rm -rf /`, `format C:`, `curl \| sh`, fork bombs | `ALWAYS_BLOCKED_COMMANDS` regex (Win + POSIX) |
| Secret leaks in git history | `git_publish` scans staged diff (`ghp_*`, `AIza*`, `sk-*`, private keys…) |
| Secrets in child processes | stripped from environment before spawn |
| Secrets in logs/sessions | redaction on write |
| Blind autonomous writes/runs | per-action approval in BUILD mode (optional, session allowlist, fail-open) |

---

## 🧪 Self-Checks

```powershell
python run_all_checks.py
```

**12 mock-driven suites** — foundations, streaming, OpenAI-compatible wire formats,
sessions + redaction, config schema, sandbox (Win+POSIX), git_publish scenarios, voice
engines, plugins, webhooks (HMAC, PR flow), the update engine (versions, cache,
anti-loop, download safety), and the scheduler (cron semantics incl. weekday offset,
row contract, history cap, minute dedup). A green run means it is safe to push.

---

## 🗺️ Roadmap

**Done**

- [x] Secure foundation: mode gate, path sandbox, sensitive-file block
- [x] Multi-provider router (Gemini + OpenAI-compatible + local Ollama)
- [x] Streaming chat with cooperative abort
- [x] Session persistence with secret redaction
- [x] n8n & Activepieces workflow export
- [x] `git_publish` with secret pre-scan
- [x] Sub-agent framework (5 dinosaur specialists)
- [x] Voice input (Whisper via Gemini/OpenAI/offline)
- [x] Plugin system
- [x] Webhook review engine (signature → review → comment)
- [x] Windows installer + cross-platform release workflow
- [x] Auto-update: daily check → download → install (opt-out per step)
- [x] Per-action approval in BUILD mode — confirm each write/run (session allowlist, fail-open when off)

**Next — must-haves for a serious native agent (prioritized)**

- [ ] **Checkpoints & `/undo`** — git snapshot per agent step, instant rollback of bad edits
- [ ] **`/init` + `REX.md` project memory** — per-project + global custom instructions the agent always reads
- [ ] **Context compaction** — auto-summarize long sessions instead of truncating history
- [ ] **Repo map** — git-aware project overview injected into prompts (like Aider)
- [ ] **Headless mode** — `rex -p "prompt" --json` for scripts and CI
- [ ] **Token & cost tracking** — `/cost` per session/provider
- [ ] **Diff review** — `/diff` before apply, approve/reject each edit
- [ ] **Auto test-run hook** — run the project's test command after edits, feed failures back
- [ ] **MCP client support** — standard tool protocol, beyond the custom plugin format
- [ ] **Webhook HTTP host + FastAPI receiver** — wire `rex/webhooks.py` to an endpoint again
- [ ] **winget/scoop distribution + code signing** — kill SmartScreen warnings for good

---

## 📄 License & Credits

<div align="center">

<img src="docs/brand/logo-text.png" width="160" alt="Rex Code">

© 2026 Husein AI Project — **MIT License** (see [`LICENSE`](LICENSE)).

Built with [Textual](https://github.com/Textualize/textual) · [Rich](https://github.com/Textualize/rich) · [google-genai](https://github.com/googleapis/python-genai) · [OpenAI SDK](https://github.com/openai/openai-python) · [FastAPI](https://fastapi.tiangolo.com) · [Pydantic](https://docs.pydantic.dev) · [PyInstaller](https://pyinstaller.org) · [Inno Setup](https://jrsoftware.org/isinfo.php)

The Rex Code dinosaur mascot is original artwork by the Husein AI Project.

</div>
