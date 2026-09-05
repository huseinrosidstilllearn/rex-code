"""
test_config.py
Self-check for rex.config normalization. Run: python test_config.py
"""
import json
import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rex.config import normalize_config, VALID_MODES, set_active_mode, load_config

def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        sys.exit(1)

# 1. Typo model gets repaired to a valid one of the active provider
cfg = {"active_provider": "gemini", "active_model": "gemini-3.6-flash", "active_mode": "build"}
out = normalize_config(cfg)
check("typo model repaired", out["active_model"] in out["providers"]["gemini"]["available_models"])

# 2. Unknown provider falls back to default
cfg = {"active_provider": "skynet", "active_model": "x", "active_mode": "plan"}
out = normalize_config(cfg)
check("unknown provider dropped", out["active_provider"] == "gemini")
check("model repaired for fallback provider", out["active_model"] in out["providers"]["gemini"]["available_models"])

# 3. Invalid mode falls back to default
cfg = {"active_provider": "gemini", "active_mode": "chaos"}
out = normalize_config(cfg)
check("invalid mode repaired", out["active_mode"] in VALID_MODES)

# 4. Valid config passes through untouched
good = {"active_provider": "9router", "active_model": "gpt-4o", "active_mode": "build",
        "providers": {"9router": {"name": "9router", "type": "openai_compatible",
                                  "base_url": "https://api.9router.com/v1", "model": "gpt-4o",
                                  "available_models": ["gpt-4o-mini", "gpt-4o"]}}}
out = normalize_config(json.loads(json.dumps(good)))
check("valid config untouched", out["active_provider"] == "9router" and out["active_model"] == "gpt-4o" and out["active_mode"] == "build")

# 5. set_active_mode rejects invalid values
try:
    set_active_mode("hack")
    check("set_active_mode rejects invalid", False)
except ValueError:
    check("set_active_mode rejects invalid", True)

# 6. Custom OpenAI-compatible provider is accepted without code changes
custom = {
    "active_provider": "token_murah",
    "active_model": "cheap-coder",
    "active_mode": "build",
    "providers": {
        "token_murah": {
            "name": "Token Murah",
            "type": "openai_compatible",
            "base_url": "https://example.test/v1",
            "api_key_env": "TOKEN_MURAH_API_KEY",
            "model": "cheap-coder",
            "available_models": ["cheap-coder"],
        }
    },
}
out = normalize_config(custom)
check("custom OpenAI-compatible provider accepted",
      out["active_provider"] == "token_murah" and out["active_model"] == "cheap-coder")

# 7. Real config.json on disk is now consistent
disk = load_config()
norm = normalize_config(json.loads(json.dumps(disk)))
check("disk config consistent",
      norm["active_model"] in norm["providers"][norm["active_provider"]]["available_models"]
      and norm["active_mode"] in VALID_MODES)

print("\nAll config checks passed.")
