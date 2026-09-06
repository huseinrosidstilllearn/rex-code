<div align="center">

![Rex Code Banner](docs/brand/banner.png)

# 🦖 Rex Code

**Autonomous AI Coding Agent — Native Windows App**

You think it, Rex builds it. PLAN before you act, BUILD when you approve —
with a sandboxed tool layer, sub-agent specialists, and one-click installer.

[![Release](https://img.shields.io/badge/Release-v0.2.0-22C55E?logo=github)](https://github.com/huseinrosidstilllearn/rex-code/releases/latest)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](#-from-source)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-0078D4?logo=windows)](#-from-source)
[![License](https://img.shields.io/badge/License-MIT-8B5CF6)](LICENSE)

**[⬇️ Download Installer](https://github.com/huseinrosidstilllearn/rex-code/releases/latest)** · [Panduan Bahasa Indonesia](PANDUAN-INSTALL.md)

</div>

---

## 🚀 Quick Install (Windows)

1. Download **`RexCode-Setup-v0.2.0-x64.exe`** from [Releases](https://github.com/huseinrosidstilllearn/rex-code/releases/latest).
2. Run it — if SmartScreen appears: **More info → Run anyway** (normal for unsigned open-source apps; see [guide](PANDUAN-INSTALL.md)).
3. Follow the wizard (EN/🇮🇩), then launch **Rex Code** from the Start Menu.
4. First run: put `GEMINI_API_KEY=...` in `%LOCALAPPDATA%\RexCode\.env` ([free key](https://aistudio.google.com)) — Rex shows you exactly where when it starts.

All user data lives in `%LOCALAPPDATA%\RexCode\` (config, sessions, logs, downloads) — never inside the install folder. Updates are checked once a day and installed automatically; every step can be switched off in `config.json → updates`.

### Linux / macOS

```bash
# Download rex-linux-x64.zip from Releases, then:
unzip rex-linux-x64.zip && cd RexCode
sh assets/linux/setup.sh     # app-menu entry + hicolor icons + 'rex' on PATH
```

`sh assets/linux/setup.sh --uninstall` removes it — user data in `~/.local/share/RexCode` is always kept. macOS: extract `rex-macos-arm64.zip` and run `./rex` (a Terminal window just opens).

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

### 📦 Install via package manager (Windows)

```powershell
winget install RexCodeTeam.RexCode        # after the winget-pkgs PR is merged
scoop bucket add extras; scoop install rexcode   # after the Extras PR is merged
```

Manifests live in [`packaging/`](packaging/README.md) and are regenerated
automatically per release.

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
| `/cost` | Token usage for this session (prompt / completion / total). |
| `/init` | Create `REX.md` — project instructions Rex reads every session. |
| `/checkpoints` `/undo` `/redo` | Inspect & roll back automatic BUILD-action snapshots. |
| `/todos` | Show the agent todo board for this session. |
| `/files` | List workspace files. |
| `/sessions` `/new` `/use <id>` `/delete <id>` | Session management. |
| `/<custom>` | Any `.rex/commands/*.md` file you drop in — see below. |
| `/help` `/exit` | You guessed it. |

The TUI adds a **Ctrl+P command palette** and `/theme` (rex, mono, amber, cyan, violet, rose, custom `#RRGGBB`).

### Custom slash commands (`.rex/commands/`)

Any Markdown file in `<workspace>/.rex/commands/` becomes a slash command — the filename is the command:

```markdown
<!-- .rex/commands/review.md -->
---
description: Ulas kode dengan fokus keamanan
---
Anda adalah reviewer. Audit kode berikut: $ARGUMENTS
```

- `/review src/app.py` sends the body with `$ARGUMENTS` replaced by `src/app.py` (arguments are appended when the placeholder is absent).
- Front-matter `description:` shows in `/help` and the command palette.
- Names are lowercase `[a-z0-9_-]`, max 32 chars; files colliding with built-in commands are ignored (built-ins always win).
- The body runs as a normal user prompt — every tool call still goes through mode checks, approval, and checkpoints, so custom commands never add privileges.

### Headless / CI mode

```bash
rex -p "explain this repo" --json          # one-shot, structured output
rex -p "fix the failing test" --mode build # agent may write code
rex -p "run checks" --mode build --yolo    # allow destructive actions unattended (default: DENY)
rex --serve-webhook                        # start the GitHub webhook receiver (rex.webhost)
```

Exit code 0 on success, 1 on provider failure. `--json` emits `{response, mode, provider, model, session, usage, elapsed_ms}`.

### Project context (REX.md + repo map)

Rex automatically injects two context sources into every system prompt:
- **`REX.md`** in your project root (create with `/init`) plus an optional global one in the Rex data dir — conventions, prohibitions, test commands.
- **Repo map** — top-level structure, language stats, and key files; deterministic and always fresh.

Both can be toggled in `config.json → context`. Long sessions are auto-compacted: older turns get LLM-summarized into a memory note instead of being truncated (`context.max_context_tokens`, default 60k).

### MCP servers (stdio)

```json
"mcp": { "enabled": true, "servers": { "fetch": { "command": "uvx", "args": ["mcp-server-fetch"] } } }
```

Tools appear as `mcp_fetch_fetch` and merge into the tool registry like plugins. A broken server is skipped, never fatal.

### Hooks — Pre/PostToolUse

Drop a `.rex/hooks.json` in your project to run your own commands around every tool call:

```json
{
  "hooks": {
    "PreToolUse":  [{ "matcher": "run_command|delete_file", "command": "python guard.py", "timeout_sec": 10 }],
    "PostToolUse": [{ "matcher": "edit_file|apply_patch",   "command": "black ." }]
  }
}
```

Each hook receives `{"tool", "args"}` (before) or `{"tool", "args", "result"}` (after) as JSON on **stdin**. A `PreToolUse` hook that exits with code **2 denies the tool call** — its stdout becomes the reason the model sees; any other exit code, a crash, or a timeout never blocks (logged, fail-open). `PostToolUse` stdout is appended to the tool result as feedback (e.g. "auto-formatted"). Hooks run in the same sandbox as `run_command` (workspace cwd, secret-sanitized env, hard timeout), capped at 16 per event.

---

## 🧰 Agent Tools

| Tool | Mode | Purpose |
| --- | --- | --- |
| `read_file` `list_dir` `search_files` `search_content` | PLAN & BUILD | Read and explore the workspace. |
| `write_file` `edit_file` `delete_file` `apply_patch` | BUILD only | Create and modify files — `apply_patch` takes a full unified diff (multi-file, create/delete) and aborts atomically on a mismatched hunk. |
| `run_command` | BUILD only | Sandboxed shell (PowerShell / bash). |
| `run_command_bg` `task_output` `task_kill` | BUILD to start | Long-running commands detached from the round: start in background, tail output, kill. |
| `git_status` `git_publish` | BUILD for publish | Stage → secret-scan → commit → push. |
| `todo_write` | PLAN & BUILD | Agent task board — plan steps and mark progress; shown live in the status bar. |
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

## 🔔 Webhook / CI Review

`rex/webhooks.py` verifies GitHub HMAC signatures, filters PR/comment events, builds PR
context, runs a review, and posts the 🦖 comment back. `rex/webhost.py` exposes that engine
over HTTP so GitHub can deliver webhooks straight to Rex Code (30 checks):

```bash
# 1. Set environment variables (token + webhook secret)
set GITHUB_TOKEN=ghp_...
set GITHUB_WEBHOOK_SECRET=s3cret

# 2. Start the receiver (binds 127.0.0.1:8765 by default)
rex --serve-webhook          # or: python -m rex.webhost
python -m rex.webhost --host 0.0.0.0 --port 9000   # custom bind (use a TLS proxy)

# 3. Point GitHub → Settings → Webhooks at your host
#    Payload URL: http://your-host:8765/webhook/github
#    Content type: application/json · Secret: same as GITHUB_WEBHOOK_SECRET
#    Events: Pull requests, Issue comments
```

- `POST /webhook/github` — signature-verified delivery → `202 accepted` (review dispatched),
  `200 ignored` (valid but nothing to do), `403 forbidden` (bad signature), `413` oversized.
- `GET /healthz` — liveness probe for monitoring / reverse proxies.
- Config: `config.json → webhook` (`enabled`, `host`, `port`, `secret_env`, `token_env`,
  `events`, `trigger_word`, `auto_review`). `enabled: false` → the host refuses to start
  (deny by default) and the default bind is loopback-only, so exposing it is a deliberate act.

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────┐
│  Native TUI (rex/tui)        Classic CLI (cli.py)        │
│       Webhook host (rex/webhost.py)                      │
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

**30 mock-driven suites** — foundations, streaming, OpenAI-compatible wire formats,
sessions + redaction, config schema, sandbox (Win+POSIX), git_publish scenarios, voice
engines, plugins, webhooks (HMAC, PR flow, HTTP host), the update engine (versions, cache,
anti-loop, download safety), the scheduler (cron semantics incl. weekday offset,
row contract, history cap, minute dedup), the distribution manifests
(winget/scoop render integrity vs `rex/__init__.py` + `rexcode.iss`), and brand-asset
integrity (icon formats, installer wizard art, Linux desktop files vs the asset pack).
A green run means it is safe to push.

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
- [x] **Retry & backoff** — exponential backoff with jitter on 429/5xx/timeouts; 401/403 fail fast
- [x] **Token usage & `/cost`** — per-session prompt/completion/total token tracking
- [x] **`/init` + `REX.md` project memory** — per-project + global instructions injected every session
- [x] **Repo map** — deterministic project overview (structure, languages, key files) in the system prompt
- [x] **Headless mode** — `rex -p "prompt" --json` for scripts and CI (deny-by-default on destructive actions)
- [x] **Checkpoints & `/undo`** — shadow-git snapshot per BUILD action, instant rollback + `/redo`
- [x] **Context compaction** — auto-summarize long sessions via LLM instead of truncating
- [x] **MCP client (stdio + HTTP)** — Model Context Protocol servers exposed as agent tools (`mcp_<server>_<tool>`)
- [x] **Checksum-verified updates** — SHA256 checked against the release's SHA256SUMS.txt before auto-install
- [x] **Approval gate for external tools** — MCP/plugin tools confirm like built-in destructive tools; errors secret-redacted
- [x] **Provider fallback chain** — `providers_fallback` config; failed provider retries the round on the next one
- [x] **`/diff` + `/doctor` + test hook** — session change review, install health check, auto test-run convention
- [x] **`/stats`** — local token usage & cost estimate per session/day (`model_costs` config)
- [x] **`/commit` + `/pr`** — AI-generated conventional commit message & PR description from the real diff
- [x] **Multimodal + `@file`** — send images (vision) and inject files into any message
- [x] **`rex plugin add <git-url>`** — install community plugins from git
- [x] **Update channels** — stable / beta (prereleases)
- [x] **`/ask` + `/imports`** — local code index: symbol search and import graph
- [x] **'Open Rex Code here'** — Explorer right-click menu + project-scoped mode (REX_WORKSPACE)
- [x] **Post-update changelog** — release notes shown once after updating
- [x] **Webhook HTTP host** — `rex --serve-webhook` / `python -m rex.webhost`: stdlib `ThreadingHTTPServer` exposing the review engine at `POST /webhook/github` (+ `/healthz`), no new dependencies, deny-by-default
- [x] **winget/scoop manifests** — auto-generated per release (`packaging/`), CI attaches them to the release; PR to the public registries is the last manual step
- [x] **Custom slash commands** — drop a Markdown file in `.rex/commands/`, get a new `/command` (`$ARGUMENTS` substitution, front-matter description, built-ins can never be shadowed)
- [x] **Agent todo list** — `todo_write` tool + live progress in the status bar; board persisted per session (`.rex/todos/`), `/todos` to inspect
- [x] **`apply_patch`** — unified-diff tool (multi-file, create/delete, fuzzy context matching like `patch(1)`); atomic: a mismatched hunk writes nothing
- [x] **`/cost` + usage meter** — session token/cost accounting moved into `rex/usage.py`: per-model breakdown, `model_costs`-driven estimate, live `1.8k tok · ~$0.0021` status-bar footer, richer `/cost` summary
- [x] **Token budget guard** — set `token_budget` (total tokens per session, 0 = off): yellow warning at 80%, hard stop at 100% — the next run is refused before any provider call until the budget is raised
- [x] **Pre/PostToolUse hooks** — `.rex/hooks.json` runs your commands around every tool call: exit 2 on `PreToolUse` denies the call (stdout = reason), `PostToolUse` stdout is fed back to the model; sandboxed, fail-open, covers built-in + plugin + MCP tools
- [x] **Session resume** — crash recovery auto-resumes the interrupted conversation on next start; `/resume` lists the last 8 sessions and `/resume <n>` switches with full history reloaded; `/new` starts fresh; clean exits are marked so they never trigger recovery
- [x] **`/rewind` timeline** — numbered checkpoint timeline with one-command restore: `/rewind <n>` rolls the workspace back N checkpoints; uncommitted work is auto-saved and `/redo` reverses the rewind
- [x] **Background shell tasks** — `run_command_bg` starts long-running commands (dev servers, builds) without blocking the conversation; `task_output` tails output (optional wait up to 30s) and `task_kill` stops them; same sandbox, approval gate and checkpoint as `run_command`, max 8 concurrent
- [x] **`/status` report** — one aggregated health view across every subsystem: version, provider + API keys, fallback chain, MCP servers, plugins, hooks, scheduler jobs, sessions, checkpoints, updater, approval and token budget — config-level only, instant, side-effect free
- [x] **`web_search` + `web_fetch`** — read-only research tools (DuckDuckGo HTML, no API key, no new dependency); private/link-local hosts and non-http schemes blocked (SSRF-safe), optional domain allowlist (`web.allowed_domains`), every response secret-redacted and size-capped, approval-gateable
- [x] **`@` autocomplete + `@file:symbol`** — typing `@` in the TUI suggests files (Tab to complete/cycle); `@path/file.py:ClassName` inlines only that symbol's source span instead of the whole file (code-index powered)
- [x] **`/compare` multi-model** — one prompt fanned out in parallel to the active provider + fallback chain (up to 3), answers rendered side-by-side with timing; a failing variant shows its error without affecting the others

**Next — must-haves for a serious native agent (prioritized)**

- [ ] **Code signing** — kill SmartScreen warnings for good (SignPath Foundation, in application)

---

## 📄 License & Credits

<div align="center">

<img src="docs/brand/logo-text.png" width="160" alt="Rex Code">

© 2026 Husein AI Project — **MIT License** (see [`LICENSE`](LICENSE)).

Built with [Textual](https://github.com/Textualize/textual) · [Rich](https://github.com/Textualize/rich) · [google-genai](https://github.com/googleapis/python-genai) · [OpenAI SDK](https://github.com/openai/openai-python) · [FastAPI](https://fastapi.tiangolo.com) · [Pydantic](https://docs.pydantic.dev) · [PyInstaller](https://pyinstaller.org) · [Inno Setup](https://jrsoftware.org/isinfo.php)

The Rex Code dinosaur mascot is original artwork by the Husein AI Project.

</div>
