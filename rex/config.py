"""
rex.config
Configuration manager for Rex Code.
"""

import os
import json
import sys
import shutil
from pathlib import Path
from dotenv import load_dotenv

# ============================================================
# Path resolution — works both in source and frozen (PyInstaller)
# ============================================================

def _get_data_dir() -> Path:
    """
    Return the persistent data directory.
    - Source mode: project root (repo)
    - Frozen (exe): %LOCALAPPDATA%\\RexCode (Windows) or ~/.local/share/rexcode (Unix)
    """
    if getattr(sys, "frozen", False):
        # Running as PyInstaller bundle
        if sys.platform == "win32":
            base = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        else:
            base = Path.home() / ".local" / "share"
        data_dir = base / "RexCode"
    else:
        # Running from source
        data_dir = Path(__file__).resolve().parent.parent
    return data_dir

DATA_DIR = _get_data_dir()

# Derived paths (all under DATA_DIR)
PROJECT_ROOT = DATA_DIR
WORKSPACE_DIR = DATA_DIR / "workspace"
WORKFLOWS_DIR = DATA_DIR / "workflows"
CONFIG_FILE = DATA_DIR / "config.json"
ENV_FILE = DATA_DIR / ".env"
SESSIONS_DIR = DATA_DIR / "sessions"
LOGS_DIR = DATA_DIR / "logs"
PLUGINS_DIR = DATA_DIR / "plugins"

# Ensure directories exist
for d in (WORKSPACE_DIR, WORKFLOWS_DIR, SESSIONS_DIR, LOGS_DIR, PLUGINS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Load environment variables from .env (if exists)
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)

# Copy default config.json on first run (frozen mode only)
if getattr(sys, "frozen", False) and not CONFIG_FILE.exists():
    # Try to find bundled default config
    bundled_config = Path(sys._MEIPASS) / "rex" / "config.json" if hasattr(sys, "_MEIPASS") else None
    if bundled_config and bundled_config.exists():
        shutil.copy2(bundled_config, CONFIG_FILE)
    else:
        # Fallback: create minimal config
        _minimal = {
            "active_provider": "gemini",
            "active_model": "gemini-flash-latest",
            "active_mode": "plan",
        }
        CONFIG_FILE.write_text(json.dumps(_minimal, indent=2))

DEFAULT_CONFIG = {
    "active_provider": "gemini",
    "active_model": "gemini-flash-latest",
    "active_mode": "plan",
    "providers_fallback": [],
    "test_hook": {
        "enabled": False,
        "command": "",
        "timeout_sec": 120
    },
    "model_costs": {},
    "anti_slop_enabled": True,
    "max_steps": 25,
    "terminal_timeout_sec": 45,
    "terminal_output_max_chars": 8000,
    "file_read_max_chars": 20000,
    "command_allowlist": ["python", "pip", "node", "npm", "npx", "dir", "git"],
    "router_timeout_sec": 120,
    "router_retry_attempts": 3,
    "router_retry_backoff_sec": 1,
    "max_history_messages": 40,
    "stream_enabled": True,
    "voice": {
        "engine": "auto",
        "model": "gemini-2.5-flash",
        "api_key_env": "OPENAI_API_KEY",
        "api_model": "whisper-1",
        "base_url": None,
        "local_model": "base"
    },
    "plugins": {
        "enabled": True,
        "list": []
    },
    "webhook": {
        "enabled": True,
        "secret_env": "GITHUB_WEBHOOK_SECRET",
        "token_env": "GITHUB_TOKEN",
        "events": ["pull_request", "issue_comment"],
        "trigger_word": "/rex",
        "auto_review": True,
        "max_diff_chars": 30000
    },
    "updates": {
        "enabled": True,
        "repo": "huseinrosidstilllearn/rex-code",
        "timeout_sec": 5,
        "check_interval_hours": 24,
        "auto_download": True,
        "auto_install": True,
        "download_dir": None
    },
    "approval": {
        "enabled": False,
        "actions": [],
        "allow": {}
    },
    "context": {
        "project_memory": True,
        "repo_map": True,
        "max_context_tokens": 60000
    },
    "mcp": {
        "enabled": True,
        "servers": {}
    },
    "scheduler": {
        "enabled": True,
        "jobs": [
            {
                "id": "nightly-commit",
                "cron": "0 22 * * *",
                "prompt": "Review workspace, run tests, then git_publish with message 'chore: nightly commit'",
                "mode": "build",
                "enabled": True
            }
        ]
    },
    "providers": {
        "gemini": {
            "name": "Google Gemini",
            "type": "gemini",
            "api_key_env": "GEMINI_API_KEY",
            "model": "gemini-flash-latest",
            "available_models": ["gemini-flash-latest", "gemini-2.5-flash", "gemini-2.5-pro"]
        },
        "9router": {
            "name": "9router",
            "type": "openai_compatible",
            "base_url": os.getenv("NINE_ROUTER_BASE_URL", "https://api.9router.com/v1"),
            "api_key_env": "NINE_ROUTER_API_KEY",
            "model": "gpt-4o-mini",
            "available_models": ["gpt-4o-mini", "gpt-4o", "claude-3-5-sonnet", "deepseek-v3"]
        },
        "omniroute": {
            "name": "OmniRoute / OpenRouter",
            "type": "openai_compatible",
            "base_url": os.getenv("OMNI_ROUTE_BASE_URL", "https://api.openrouter.ai/v1"),
            "api_key_env": "OMNI_ROUTE_API_KEY",
            "model": "google/gemini-2.5-flash",
            "available_models": ["google/gemini-2.5-flash", "anthropic/claude-3.5-sonnet", "openai/gpt-4o", "deepseek/deepseek-chat"]
        },
        "custom": {
            "name": "Custom OpenAI / Local Ollama",
            "type": "openai_compatible",
            "base_url": os.getenv("OPENAI_BASE_URL", "http://localhost:11434/v1"),
            "api_key_env": "OPENAI_API_KEY",
            "model": "deepseek-r1",
            "available_models": ["deepseek-r1", "llama3.2", "qwen2.5-coder"]
        }
    }
}

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()

def save_config(cfg: dict) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

VALID_MODES = ("plan", "build")

def normalize_config(cfg: dict) -> dict:
    """Validate and repair config, including custom OpenAI-compatible providers."""
    defaults = DEFAULT_CONFIG["providers"]
    providers = cfg.get("providers")
    if not isinstance(providers, dict):
        providers = defaults

    valid_providers = {}
    for provider_id, raw in providers.items():
        if not isinstance(provider_id, str) or not isinstance(raw, dict):
            continue
        provider = {**defaults.get(provider_id, {}), **raw}
        provider_type = provider.get("type")
        models = provider.get("available_models")
        model = provider.get("model")

        if provider_type == "gemini":
            if provider_id != "gemini":
                continue
        elif provider_type == "openai_compatible":
            base_url = provider.get("base_url")
            if not isinstance(base_url, str) or not base_url.startswith(("http://", "https://")):
                continue
        else:
            continue

        if not isinstance(models, list):
            models = []
        models = [item for item in models if isinstance(item, str) and item.strip()]
        if isinstance(model, str) and model.strip() and model not in models:
            models.insert(0, model)
        if not models:
            continue

        provider["available_models"] = models
        provider["model"] = model if model in models else models[0]
        provider["name"] = str(provider.get("name") or provider_id)
        provider["api_key_env"] = str(provider.get("api_key_env") or "OPENAI_API_KEY")
        valid_providers[provider_id] = provider

    if "gemini" not in valid_providers:
        valid_providers["gemini"] = defaults["gemini"].copy()
    cfg["providers"] = valid_providers

    provider_id = cfg.get("active_provider", DEFAULT_CONFIG["active_provider"])
    if provider_id not in valid_providers:
        provider_id = DEFAULT_CONFIG["active_provider"]
        cfg["active_provider"] = provider_id

    available = valid_providers[provider_id]["available_models"]
    if cfg.get("active_model") not in available:
        cfg["active_model"] = valid_providers[provider_id]["model"]

    mode = str(cfg.get("active_mode", DEFAULT_CONFIG["active_mode"])).lower()
    cfg["active_mode"] = mode if mode in VALID_MODES else DEFAULT_CONFIG["active_mode"]

    fallback = cfg.get("providers_fallback")
    if not isinstance(fallback, list):
        fallback = []
    seen = set()
    cleaned_fallback = []
    for item in fallback:
        if isinstance(item, str) and item.strip() and item not in seen:
            seen.add(item)
            cleaned_fallback.append(item)
    cfg["providers_fallback"] = cleaned_fallback

    hook_defaults = DEFAULT_CONFIG["test_hook"]
    hook = cfg.get("test_hook")
    if not isinstance(hook, dict):
        hook = {}
    hook = {**hook_defaults, **hook}
    hook["enabled"] = bool(hook.get("enabled", False))
    hook["command"] = str(hook.get("command") or "").strip()
    try:
        hook["timeout_sec"] = max(5, int(hook.get("timeout_sec", 120)))
    except (TypeError, ValueError):
        hook["timeout_sec"] = hook_defaults["timeout_sec"]
    cfg["test_hook"] = hook

    model_costs = cfg.get("model_costs")
    if not isinstance(model_costs, dict):
        model_costs = {}
    cfg["model_costs"] = model_costs

    voice_defaults = DEFAULT_CONFIG["voice"]
    voice = cfg.get("voice")
    if not isinstance(voice, dict):
        voice = {}
    voice = {**voice_defaults, **voice}
    engine = str(voice.get("engine", "auto")).lower()
    if engine not in ("auto", "gemini", "openai", "local"):
        engine = "auto"
    voice["engine"] = engine
    if not isinstance(voice.get("model"), str) or not voice["model"].strip():
        voice["model"] = voice_defaults["model"]
    if not isinstance(voice.get("api_model"), str) or not voice["api_model"].strip():
        voice["api_model"] = voice_defaults["api_model"]
    if not isinstance(voice.get("api_key_env"), str) or not voice["api_key_env"].strip():
        voice["api_key_env"] = voice_defaults["api_key_env"]
    if not isinstance(voice.get("local_model"), str) or not voice["local_model"].strip():
        voice["local_model"] = voice_defaults["local_model"]
    cfg["voice"] = voice

    plugins_defaults = DEFAULT_CONFIG["plugins"]
    plugins = cfg.get("plugins")
    if not isinstance(plugins, dict):
        plugins = {}
    plugins = {**plugins_defaults, **plugins}
    plugins["enabled"] = bool(plugins.get("enabled", True))
    plugins["list"] = [str(item) for item in plugins.get("list") or [] if isinstance(item, str)]
    cfg["plugins"] = plugins

    webhook_defaults = DEFAULT_CONFIG["webhook"]
    webhook = cfg.get("webhook")
    if not isinstance(webhook, dict):
        webhook = {}
    webhook = {**webhook_defaults, **webhook}
    webhook["enabled"] = bool(webhook.get("enabled", True))
    webhook["events"] = [str(item) for item in webhook.get("events") or [] if isinstance(item, str)] or webhook_defaults["events"]
    webhook["trigger_word"] = str(webhook.get("trigger_word") or "/rex")
    if not isinstance(webhook.get("secret_env"), str) or not webhook["secret_env"].strip():
        webhook["secret_env"] = webhook_defaults["secret_env"]
    if not isinstance(webhook.get("token_env"), str) or not webhook["token_env"].strip():
        webhook["token_env"] = webhook_defaults["token_env"]
    webhook["auto_review"] = bool(webhook.get("auto_review", True))
    try:
        webhook["max_diff_chars"] = max(1000, int(webhook.get("max_diff_chars", 30000)))
    except (TypeError, ValueError):
        webhook["max_diff_chars"] = webhook_defaults["max_diff_chars"]
    cfg["webhook"] = webhook

    scheduler_defaults = DEFAULT_CONFIG["scheduler"]
    scheduler = cfg.get("scheduler")
    if not isinstance(scheduler, dict):
        scheduler = {}
    scheduler = {**scheduler_defaults, **scheduler}
    scheduler["enabled"] = bool(scheduler.get("enabled", True))
    jobs = scheduler.get("jobs")
    if not isinstance(jobs, list):
        jobs = []
    normalized_jobs = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        job_id = str(job.get("id", "")).strip()
        cron = str(job.get("cron", "")).strip()
        prompt = str(job.get("prompt", "")).strip()
        mode = str(job.get("mode", "build")).lower()
        enabled = bool(job.get("enabled", True))
        if job_id and cron and prompt and mode in VALID_MODES:
            normalized_jobs.append({
                "id": job_id,
                "cron": cron,
                "prompt": prompt,
                "mode": mode,
                "enabled": enabled
            })
    scheduler["jobs"] = normalized_jobs
    cfg["scheduler"] = scheduler

    context_defaults = DEFAULT_CONFIG["context"]
    context = cfg.get("context")
    if not isinstance(context, dict):
        context = {}
    context = {**context_defaults, **context}
    context["project_memory"] = bool(context.get("project_memory", True))
    context["repo_map"] = bool(context.get("repo_map", True))
    try:
        context["max_context_tokens"] = max(2000, int(context.get("max_context_tokens", 60000)))
    except (TypeError, ValueError):
        context["max_context_tokens"] = context_defaults["max_context_tokens"]
    cfg["context"] = context

    mcp_defaults = DEFAULT_CONFIG["mcp"]
    mcp = cfg.get("mcp")
    if not isinstance(mcp, dict):
        mcp = {}
    mcp = {**mcp_defaults, **mcp}
    mcp["enabled"] = bool(mcp.get("enabled", True))
    servers = mcp.get("servers")
    if not isinstance(servers, dict):
        servers = {}
    valid_servers = {}
    for name, server_cfg in servers.items():
        if isinstance(name, str) and name.strip() and isinstance(server_cfg, dict) and isinstance(server_cfg.get("command"), str) and server_cfg["command"].strip():
            entry = {
                "command": server_cfg["command"].strip(),
                "args": [str(a) for a in server_cfg.get("args") or []],
            }
            env = server_cfg.get("env")
            if isinstance(env, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
                entry["env"] = env
            valid_servers[name.strip()] = entry
    mcp["servers"] = valid_servers
    cfg["mcp"] = mcp

    updates_defaults = DEFAULT_CONFIG["updates"]
    updates = cfg.get("updates")
    if not isinstance(updates, dict):
        updates = {}
    updates = {**updates_defaults, **updates}
    updates["enabled"] = bool(updates.get("enabled", True))
    updates["auto_download"] = bool(updates.get("auto_download", True))
    updates["auto_install"] = bool(updates.get("auto_install", True))
    repo = str(updates.get("repo") or "").strip()
    if not repo or repo.count("/") != 1:
        repo = updates_defaults["repo"]
    updates["repo"] = repo
    try:
        updates["timeout_sec"] = max(1, min(30, float(updates.get("timeout_sec", 5))))
    except (TypeError, ValueError):
        updates["timeout_sec"] = updates_defaults["timeout_sec"]
    try:
        updates["check_interval_hours"] = max(0.25, float(updates.get("check_interval_hours", 24)))
    except (TypeError, ValueError):
        updates["check_interval_hours"] = updates_defaults["check_interval_hours"]
    download_dir = updates.get("download_dir")
    if download_dir is not None and (not isinstance(download_dir, str) or not download_dir.strip()):
        download_dir = None
    updates["download_dir"] = download_dir
    cfg["updates"] = updates

    approval_defaults = DEFAULT_CONFIG["approval"]
    approval = cfg.get("approval")
    if not isinstance(approval, dict):
        approval = {}
    approval = {**approval_defaults, **approval}
    approval["enabled"] = bool(approval.get("enabled", False))
    actions = approval.get("actions")
    if not isinstance(actions, list):
        actions = []
    approval["actions"] = sorted({item.strip() for item in actions if isinstance(item, str) and item.strip()})
    allow = approval.get("allow")
    if not isinstance(allow, dict):
        allow = {}
    approval["allow"] = {
        str(key): [str(p) for p in (value if isinstance(value, list) else [value]) if isinstance(p, str)]
        for key, value in allow.items()
    }
    cfg["approval"] = approval
    return cfg

def get_active_mode() -> str:
    return normalize_config(load_config())["active_mode"]

def set_active_mode(mode: str) -> None:
    mode = str(mode).lower()
    if mode not in VALID_MODES:
        raise ValueError(f"Mode '{mode}' tidak valid. Gunakan 'plan' atau 'build'.")
    cfg = load_config()
    cfg["active_mode"] = mode
    save_config(cfg)

def get_active_provider_info() -> tuple:
    cfg = normalize_config(load_config())
    provider_id = cfg.get("active_provider", "gemini")
    prov = cfg.get("providers", {}).get(provider_id, DEFAULT_CONFIG["providers"]["gemini"])
    model = cfg.get("active_model", prov.get("model", "gemini-flash-latest"))
    return provider_id, prov, model
