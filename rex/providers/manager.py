"""
rex.providers.manager
Factory and manager for selecting the active provider.
"""

import os
from rex.config import load_config, normalize_config
from rex.providers.base import BaseLLMProvider
from rex.providers.gemini import GeminiProvider
from rex.providers.router import OpenAIRouterProvider

def get_llm_provider() -> BaseLLMProvider:
    """
    Get the configured active provider.
    """
    cfg = normalize_config(load_config())
    provider_id = cfg["active_provider"]
    model_name = cfg["active_model"]
    provider = cfg["providers"][provider_id]
    api_key = os.getenv(provider.get("api_key_env", "OPENAI_API_KEY"), "")

    if provider.get("type") == "gemini":
        return GeminiProvider(api_key=api_key, model=model_name)

    return OpenAIRouterProvider(
        base_url=provider["base_url"],
        api_key=api_key,
        model=model_name,
        timeout_sec=cfg.get("router_timeout_sec", 120),
        retry_attempts=cfg.get("router_retry_attempts", 3),
        retry_backoff_sec=cfg.get("router_retry_backoff_sec", 1),
    )
