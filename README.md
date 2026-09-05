<div align="center">

![Rex Code Banner](docs/brand/banner.png)

# 🦖 Rex Code

**Autonomous AI Coding & Workflow Agent**

You think it, Rex builds it. A resilient, secure agent that plans, builds, and debugs software while exporting ready-to-import n8n and Activepieces automations. Plan before you act, build when you approve, and stop the loop at any time without losing state.

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](#-requirements--installation)
[![Platform](https://img.shields.io/badge/Platform-Windows-0078D4?logo=windows)](#-requirements--installation)
[![Status](https://img.shields.io/badge/Foundation-Secure%20%26%20Resilient-22C55E)](#-security-by-default)

</div>

---

## 🖼️ Screenshots

> Drop your screenshots into `docs/screenshots/` and reference them here. The placeholders below are ready to be replaced.

| File | Description |
| --- | --- |
| `docs/screenshots/dashboard-overview.png` | Full dashboard: chat, Plan/Build toggle, provider selector, file explorer, n8n tab. |
| `docs/screenshots/plan-mode.png` | PLAN mode output: architecture notes, file tree, safe read-only preview. |
| `docs/screenshots/build-mode.png` | BUILD mode output: tool calls, file writes, terminal execution, auto-debug loop. |
| `docs/screenshots/cli-session.png` | CLI session with `/sessions`, `/models`, and `/n8n` commands. |

```markdown
![Dashboard overview](docs/screenshots/dashboard-overview.png)
![Plan mode](docs/screenshots/plan-mode.png)
![Build mode](docs/screenshots/build-mode.png)
![CLI session](docs/screenshots/cli-session.png)
```

---

## ✨ What Rex Code Can Do

- **Two modes, one brain.** PLAN mode researches and writes a plan without touching files. BUILD mode writes code, runs commands, and auto-debugs until it works.
- **ReAct loop with self-healing.** Every tool result feeds the next thought. Terminal errors trigger automatic code fixes and re-runs.
- **Multi-provider.** Switch between Google Gemini and OpenAI-compatible APIs (9router, OmniRoute/OpenRouter, custom, local Ollama) without changing prompts.
- **Cooperative abort.** Press **Stop** in the dashboard or interrupt in the CLI. The current tool may finish, but the next step never runs.
- **n8n & Activepieces export.** Generate webhook-AI workflow JSON in `workflows/` and import it directly into your automation platform.
- **Anti-slop guardrail.** Strips AI clichés (`leverage`, `tapestry`, `game changer`) and keeps output natural.
- **Local sessions.** Conversation history survives browser refresh and CLI restarts. Secrets and long outputs are redacted before saving.
- **Hard security rails.** Path traversal, sensitive files, and dangerous shell commands are blocked. Secrets never enter child processes.

---
## 🎬 One-Liner Start

Double-click a launcher. That is the whole story.

| Launcher | What it does |
| --- | --- |
| `start_web.bat` | Opens the FastAPI dashboard at `http://localhost:8000` and your browser. |
| `start_cli.bat` | Opens a Claude-Code-style terminal with rich formatting and instant responses. |

Both scripts use the local `.venv` Python, so no global installation is required.

---

## 🛠️ Requirements & Installation

Rex Code runs entirely on your machine. It targets **Windows** (PowerShell) with **Python 3.10+**.

1. **Clone the repository**
   ```powershell
   git clone https://github.com/husein-rexcode/rex-code.git
   cd "rex-code"
   ```
2. **Create a virtual environment** (one-time, ~10 seconds)
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
3. **Configure providers** — copy `config.example.json` → `config.json` and fill in your API keys (Gemini, 9router, OpenAI-compatible, or local Ollama).
4. **Launch**
   - Dashboard: `.\start_web.bat` → open <http://localhost:8000>
   - CLI: `.\start_cli.bat` → interactive shell

> Secrets are read from `config.json` and the `secrets/` directory. **Never commit these files.** The repository ships a pre-wired `.gitignore` that excludes them.

---

## 🚀 Usage

### 1. Dashboard (FastAPI + Browser)

```powershell
python app.py
```

Visit `http://localhost:8000`. The UI exposes:

| Tab | Purpose |
| --- | --- |
| **Chat** | Streaming conversation with markdown rendering and copy-as-markdown. |
| **Tools** | Live trace of every tool call (read/write/edit/run/git). |
| **Files** | Workspace tree with upload, download, delete. |
| **n8n** | Generate & download webhook-AI workflow JSON. |
| **Sessions** | Resume, rename, or delete saved conversations. |

### 2. CLI (Claude Code-style)

```powershell
python cli.py
```

Useful slash commands:

| Command | Effect |
| --- | --- |
| `/plan` | Switch to PLAN (read-only) mode. |
| `/build` | Switch to BUILD (autonomous) mode. |
| `/models` | Pick provider + model without restarting. |
| `/n8n` | Generate an n8n workflow template. |
| `/anti-slop` | Audit & clean text from AI clichés. |
| `/files` | List files in the workspace. |
| `/sessions` `/new` `/use <id>` `/delete <id>` | Session management. |
| `/help` `/exit` | Self-explanatory. |

While a tool is running you will see a custom **green dinosaur spinner** (`BRAND_GREEN #22C55E`) to confirm the agent is alive.

---

## 🏗️ Architecture

<img src="docs/brand/logo-main.png" width="140" align="right" alt="Rex Code logo">

Rex Code is structured as a thin orchestration layer over a ReAct loop, with strict boundaries between planning and execution.

```
┌─────────────────────────────────────────────────────────────┐
│  CLI (cli.py)         FastAPI Dashboard (app.py)            │
│        ↓                        ↓                            │
│  RexAgent.run() — ReAct loop with StepEvent callbacks       │
│        ↓                                                    │
│  Tool layer (rex/tools.py)                                  │
│  ├── read_file / write_file / edit_file / delete_file       │
│  ├── list_dir / search_files / search_content               │
│  ├── run_command (sandboxed via ALWAYS_BLOCKED_COMMANDS)    │
│  ├── git_status / git_publish (secret-scan guarded)         │
│  └── session_store (rex/sessions.py)                        │
│        ↓                                                    │
│  Provider router (rex/providers/) — Gemini, 9router,        │
│  OpenAI-compatible, local Ollama                             │
│        ↓                                                    │
│  Anti-slop filter (rex/anti_slop.py) — strips AI clichés    │
└─────────────────────────────────────────────────────────────┘
```

**Key invariants**

- **Mode gate** — every write/run tool checks `get_active_mode()` and refuses to execute in PLAN.
- **Path safety** — `resolve_path()` blocks `..` traversal; `_is_sensitive()` rejects `.env`, `*.pem`, `*.key`, etc.
- **Secret redaction** — sessions are sanitised before persistence.
- **Cooperative abort** — `Stop` flag in dashboard / `Ctrl+C` in CLI sets a flag the ReAct loop checks between steps.

---

## 🛡️ Security by Default

| Threat | Defense | Code |
| --- | --- | --- |
| Path traversal (`../etc/passwd`) | `resolve_path` + `is_relative_to` | `rex/tools.py` |
| Editing `.env` / `*.pem` / `*.key` | `_is_sensitive()` allow-list | `rex/tools.py` |
| `rm -rf /`, `format C:`, `Invoke-Expression` | `ALWAYS_BLOCKED_COMMANDS` regex | `rex/tools.py` |
| Leaking secrets in git history | `git_publish` scans staged diff for `ghp_*`, `AIza*`, `BEGIN PRIVATE KEY`, etc. | `rex/tools.py` |
| Pushing too many files at once | `git_publish_max_files` (default 50) | `rex/config.py` |
| API keys landing in logs | `secrets/` dir is `.gitignore`d; outputs are redacted on write | `.gitignore`, `rex/sessions.py` |

Default secret patterns in `DEFAULT_SECRET_PATTERNS`:

```python
DEFAULT_SECRET_PATTERNS = (
    r"ghp_[A-Za-z0-9]{20,}",          # GitHub personal token
    r"github_pat_[A-Za-z0-9_]{20,}",  # GitHub fine-grained token
    r"AIza[A-Za-z0-9_-]{30,}",        # Google API key
    r"sk-[A-Za-z0-9]{20,}",           # OpenAI / Anthropic key
    r"BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY",
)
```

You can extend this list in `config.json` under `git_publish_block_patterns`.

---

## 🧪 Self-Checks

Run the full pre-push audit:

```powershell
python run_all_checks.py
```

It chains 7 mock-driven test suites:

| Suite | What it verifies |
| --- | --- |
| `test_foundations.py` | Config loading, mode toggling, workspace bootstrap. |
| `test_streaming.py` | SSE chunks, cancel signal, partial JSON. |
| `test_openai_compatible.py` | 9router / OmniRoute / Ollama wire formats. |
| `test_sessions.py` | Create / resume / delete + secret redaction. |
| `test_config.py` | `config.json` schema validation. |
| `test_sandbox.py` | Path traversal, command blocking, sensitive files. |
| `test_git_publish.py` | 10 scenarios: plan/empty/no-origin/no-changes/secret/too-many/success. |

A green run means the foundation is safe to push.

---

## 🧰 Available Tools

The agent (and the dashboard's "Tools" tab) can invoke any of these:

| Tool | Mode | Purpose |
| --- | --- | --- |
| `read_file` | PLAN & BUILD | Read a workspace file. |
| `write_file` | BUILD only | Create / overwrite a file. |
| `edit_file` | BUILD only | Surgical text replacement. |
| `list_dir` | PLAN & BUILD | Tree of the workspace. |
| `search_files` | PLAN & BUILD | Find files by name. |
| `search_content` | PLAN & BUILD | Grep workspace with line numbers. |
| `delete_file` | BUILD only | Remove a single file. |
| `run_command` | BUILD only | Run a PowerShell command in a sandbox. |
| `git_status` | PLAN & BUILD | Short + branch git summary. |
| `git_publish` | BUILD only | Stage → secret-scan → commit → push. |

The full schema is exported via `TOOL_DEFINITIONS` in `rex/tools.py` for any OpenAI-compatible LLM.

---

## 🗺️ Roadmap

- [x] Secure foundation: mode gate, path sandbox, sensitive-file block.
- [x] Multi-provider router (Gemini + OpenAI-compatible + local).
- [x] Streaming chat with cooperative abort.
- [x] Session persistence with secret redaction.
- [x] n8n & Activepieces workflow export.
- [x] `git_publish` tool with secret pre-scan.
- [x] Brand assets + dinosaur spinner.
- [ ] Voice input (Whisper) for CLI & dashboard.
- [ ] Plugin system for community-contributed tools.
- [ ] Docker image for Linux / macOS.
- [ ] Webhook trigger: run Rex from CI on PR events.

---

## 📄 License & Credits

<img src="docs/brand/logo-text.png" width="160" alt="Rex Code">

© 2026 Husein AI Project. Released under the **MIT License** — see `LICENSE`.

Built with:

- [Rich](https://github.com/Textualize/rich) — terminal rendering.
- [FastAPI](https://fastapi.tiangolo.com/) — async dashboard.
- [Pydantic](https://docs.pydantic.dev/) — config validation.
- The **Rex Code dinosaur** mascot is original artwork by the Husein AI Project.
