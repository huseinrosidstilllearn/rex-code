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

## ✨ What Rex Code Can Do

- **Two modes, one brain.** PLAN mode researches and writes a plan without touching files. BUILD mode writes code, runs commands, and auto-debugs until it works.
- **ReAct loop with self-healing.** Every tool result feeds the next thought. Terminal errors trigger automatic code fixes and re-runs.
- **Multi-provider.** Switch between Google Gemini and OpenAI-compatible APIs (9router, OmniRoute/OpenRouter, custom, local Ollama) without changing prompts.
- **Cooperative abort.** Press **Stop** in the dashboard or interrupt in the CLI. The current tool may finish, but the next step never runs.
- **n8n & Activepieces export.** Generate webhook-AI workflow JSON in `workflows/` and import it directly into your automation platform.
- **Anti-slop guardrail.** Strips AI clichés (`leverage`, `tapestry`, `game changer`) and keeps output natural.
- **Local sessions.** Conversation history survives browser refresh and CLI restarts. Secrets and long outputs are redacted before saving.
- **Hard security rails.** Path traversal, sensitive files, and dangerous shell commands are blocked. Secrets never enter child processes.
- **🦕 Sub-Agent Specialists.** Five read-only dinosaur analysts (Brachio, Raptor, Trike, Ptero, Dilo) that you can delegate to for code review, bug hunting, security auditing, architecture analysis, and quality audits — all in Plan mode with anti-recursion protection.
- **Claude-Code-style CLI.** Rich ANSI Shadow block-letter banner, welcome panel with mode/provider/model/workspace, and beautiful per-agent report panels with ASCII art faces.

---
## 🎬 One-Liner Start

Double-click a launcher. That is the whole story.

| Launcher | What it does |
| --- | --- |
| `start_web.bat` | Opens the FastAPI dashboard at `http://localhost:8000` and your browser. |
| `start_cli.bat` | Opens a Claude-Code-style terminal with rich formatting and instant responses. |

Both scripts use the local `.venv` Python, so no global installation is required.

---

## 📦 Windows Installer (EXE)

Rex Code ships as a real Windows installer: `RexCode-Setup-vX.Y.Z-x64.exe`.

**Install** — run the setup exe and choose your options:

- Install dir: `C:\Program Files\RexCode` (default)
- Desktop / Start Menu shortcuts
- *Add to PATH* → call `rex` from any terminal
- *Keep user data* → config, sessions, and logs survive uninstall

**First run** — all user data lives in `%LOCALAPPDATA%\RexCode` (never inside the install folder):

```
%LOCALAPPDATA%\RexCode\
├── config.json   ← auto-copied from the bundled default on first run
├── .env          ← put your GEMINI_API_KEY here (see .env.example)
├── workspace/  sessions/  logs/  plugins/
```

**Rebuild the installer yourself** (one command):

```bat
installer\windows\build_installer.bat
```

The script chains PyInstaller (bundle build) → frozen-exe smoke test → Inno Setup compile, and reads the version from `rex/__init__.py`. You need the repo `.venv` (with `pyinstaller`) and [Inno Setup 6](https://jrsoftware.org/isinfo.php) — `winget install -e --id JRSoftware.InnoSetup`.

**Other OSes** — push a tag (`git tag v1.0.1 && git push origin v1.0.1`) and `.github/workflows/release.yml` builds the Windows installer plus zipped Linux/macOS binaries, attaching everything to the GitHub Release automatically.

**Uninstall** — Windows Settings → Apps → Rex Code. Untick *Keep user data* during uninstall to also remove `%LOCALAPPDATA%\RexCode`.

### 🔄 Auto-update

Rex checks the GitHub Releases API **at most once per day** (cached in `%LOCALAPPDATA%\RexCode\logs\last_update_check.json`) and never blocks startup — offline, rate-limited, or release-less states are silent skips.

When a newer version exists, Rex shows a one-line notice and (by default) downloads the installer to `%LOCALAPPDATA%\RexCode\downloads\` and launches it — Windows shows its own UAC prompt and the Inno wizard takes over. An anti-loop guard makes auto-install run at most **once per version number**, so cancelling the wizard never triggers endless re-launches.

All three steps are switchable in `config.json` → `updates`:

| Key | Default | Meaning |
| --- | --- | --- |
| `enabled` | `true` | Check for updates at startup |
| `auto_download` | `true` | Download the installer automatically |
| `auto_install` | `true` | Launch the installer after download |
| `check_interval_hours` | `24` | Minimum interval between checks |

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
| `/voice` | Record your voice, get Whisper transcription as the next instruction (CLI). |
| `/files` | List files in the workspace. |
| `/sessions` `/new` `/use <id>` `/delete <id>` | Session management. |
| `/help` `/exit` | Self-explanatory. |

While a tool is running you will see a custom **green dinosaur spinner** (`BRAND_GREEN #22C55E`) to confirm the agent is alive.

---

## 🎙️ Voice Input (Whisper)

Dictate instructions instead of typing them. No new dependencies required for the default path.

- **Dashboard** — click the **🎤 Suara** button next to the input bar, speak, click again. The recording is transcribed and dropped into the input for you to review before sending.
- **CLI** — type `/voice`, speak, press **Enter** to stop. The transcription becomes your next instruction automatically.

Transcription engines are configured under `voice` in `config.json` (`engine`: `auto` by default):

| Engine | Backend | Requirements |
| --- | --- | --- |
| `gemini` | Google Gemini (audio-capable model) | `GEMINI_API_KEY` — already used by the default provider |
| `openai` | OpenAI `/audio/transcriptions` (Whisper) | `OPENAI_API_KEY` (+ optional `base_url` for compatible providers) |
| `local` | `faster-whisper` (fully offline) | `pip install faster-whisper` |

With `auto`, engines are tried in order (`gemini` → `openai` → `local`) and each is skipped when its key or package is missing. CLI mic capture additionally needs `pip install sounddevice numpy`.

---

## 🧩 Plugin System

Community-contributed tools load from the `plugins/` directory without touching `rex/tools.py`. Each plugin is a single file (`plugins/<name>.py`) or a package (`plugins/<name>/plugin.py`) exposing `PLUGIN_TOOLS`:

```python
PLUGIN_TOOLS = [{
    "name": "current_time",
    "description": "Mengembalikan waktu lokal saat ini.",
    "parameters": {"type": "object", "properties": {
        "timezone": {"type": "string", "description": "zona IANA (opsional)"}},
        "required": []},
    "handler": my_handler,  # callable; kwargs match parameters
}]
```

- Shipped example: `plugins/current_time.py` — try `current_time(timezone="Asia/Jakarta")`.
- Enable/disable in `config.json`: `"plugins": {"enabled": true, "list": []}` (empty `list` = load all).
- Plugin tools are merged into the LLM tool schema automatically for **both** the OpenAI-compatible router and the Gemini provider (the Gemini tool list is built dynamically from the merged registry).
- Broken plugins are isolated: they log a warning and never crash the agent.

---

## 🔔 Webhook Trigger (Run Rex from CI)

Rex Code can review Pull Requests automatically when GitHub sends a webhook — no human in the loop.

1. **Set up secrets** in `.env`:
   ```
   GITHUB_WEBHOOK_SECRET=random-secret-anda
   GITHUB_TOKEN=github_pat_xxx   # token dengan izin read/write issues & PR
   ```
2. **Register the webhook** in your repo: *Settings → Webhooks → Add webhook*:
   - Payload URL: `https://your-host:8000/api/webhook/github`
   - Content type: `application/json`
   - Secret: the same `GITHUB_WEBHOOK_SECRET`
   - Events: **Pull requests** and **Issue comments** (or "Let me select" → both).
3. **How it behaves**: every PR *opened* / *synchronize* gets an automatic 🦖 Rex Code review comment; typing `/rex ...` in a PR comment triggers a review on demand.

Security rails: every delivery must carry a valid `X-Hub-Signature-256` HMAC (else `403`); the GitHub token is never logged and is stripped from child process environments. Configuration lives under `webhook` in `config.json` (event filters, trigger word, `auto_review`, diff size cap).

Local test without GitHub:
```bash
curl -X POST http://localhost:8000/api/webhook/github \
  -H "X-GitHub-Event: pull_request" \
  -H "X-Hub-Signature-256: sha256=$(python -c "import hmac,hashlib;print(hmac.new(b'RAHASIA',open('p.json','rb').read(),hashlib.sha256).hexdigest())")" \
  --data-binary @p.json
```

---

## 🐳 Docker (Linux / macOS)

The dashboard, webhook receiver, and plugin system run in a container on any platform:

```bash
docker compose up --build
# open http://localhost:8000
```

- `config.json`, `workspace/`, `workflows/`, `sessions/`, and `logs/` are mounted as volumes; secrets come from `.env` at runtime (never baked into the image).
- Runs as a non-root user with a healthcheck.
- `run_command` is platform-aware: **PowerShell on Windows, `bash` on Linux/macOS** (`rex/shell.py`), and the sandbox blocks POSIX danger families too — `rm -rf /`, `sudo`, `curl|sh`, `dd if=/dev/zero`, fork bombs, and more (see `test_sandbox.py`).

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
│  Tool layer (rex/tools.py + rex/plugins.py)                 │
│  ├── read_file / write_file / edit_file / delete_file       │
│  ├── list_dir / search_files / search_content               │
│  ├── run_command (sandboxed via ALWAYS_BLOCKED_COMMANDS)    │
│  ├── git_status / git_publish (secret-scan guarded)         │
│  ├── plugin tools (plugins/ dir, community-contributed)     │
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

It chains 10 mock-driven test suites:

| Suite | What it verifies |
| --- | --- |
| `test_foundations.py` | Config loading, mode toggling, workspace bootstrap. |
| `test_streaming.py` | SSE chunks, cancel signal, partial JSON. |
| `test_openai_compatible.py` | 9router / OmniRoute / Ollama wire formats. |
| `test_sessions.py` | Create / resume / delete + secret redaction. |
| `test_config.py` | `config.json` schema validation. |
| `test_sandbox.py` | Path traversal, command blocking, sensitive files. |
| `test_git_publish.py` | 10 scenarios: plan/empty/no-origin/no-changes/secret/too-many/success. |
| `test_voice.py` | Engine fallback, config repair, missing keys/packages, mime mapping. |
| `test_plugins.py` | Discovery, config gating, broken-plugin isolation, Gemini wrapping. |
| `test_webhooks.py` | Signatures, event filtering, PR context, mocked end-to-end review. |

A green run means the foundation is safe to push.

---

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
| **`delegate_to_brachio`** | PLAN only | Delegate code review & general analysis (read-only). |
| **`delegate_to_raptor`** | PLAN only | Delegate bug hunting & traceback analysis (read-only). |
| **`delegate_to_trike`** | PLAN only | Delegate security auditing & vulnerability scanning (read-only). |
| **`delegate_to_ptero`** | PLAN only | Delegate architecture & documentation analysis (read-only). |
| **`delegate_to_dilo`** | PLAN only | Delegate quality auditing & anti-slop detection (read-only). |

The full schema is exported via `TOOL_DEFINITIONS` in `rex/tools.py` for any OpenAI-compatible LLM.
## 🧰 Available Tools

The agent (and the dashboard's "Tools" tab) can invoke any of these:

| Tool | Mode | Purpose |
## 🗺️ Roadmap

- [x] Secure foundation: mode gate, path sandbox, sensitive-file block.
- [x] Multi-provider router (Gemini + OpenAI-compatible + local).
- [x] Streaming chat with cooperative abort.
- [x] Session persistence with secret redaction.
- [x] n8n & Activepieces workflow export.
- [x] `git_publish` tool with secret pre-scan.
- [x] **🦕 Sub-Agent Framework** + 5 specialized dinosaur agents (Brachio, Raptor, Trike, Ptero, Dilo).
- [x] Brand assets + dinosaur spinner.
- [x] Voice input (Whisper) for CLI & dashboard.
- [x] Plugin system for community-contributed tools.
- [x] Webhook trigger: run Rex from CI on PR events.
- [x] Docker image for Linux / macOS.
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
- [x] Voice input (Whisper) for CLI & dashboard.
- [x] Plugin system for community-contributed tools.
- [x] Webhook trigger: run Rex from CI on PR events.
- [x] Docker image for Linux / macOS.
- [x] Windows installer (EXE) + cross-platform release workflow.
- [x] Auto-update checker (daily check → download → install, opt-out per step).

---

## 📄 License & Credits

<img src="docs/brand/logo-text.png" width="160" alt="Rex Code">

© 2026 Husein AI Project. Released under the **MIT License** — see `LICENSE`.

Built with:

- [Rich](https://github.com/Textualize/rich) — terminal rendering.
- [FastAPI](https://fastapi.tiangolo.com/) — async dashboard.
- [Pydantic](https://docs.pydantic.dev/) — config validation.
- The **Rex Code dinosaur** mascot is original artwork by the Husein AI Project.
