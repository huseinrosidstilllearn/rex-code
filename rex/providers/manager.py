"""
rex.providers.manager
Factory and manager for selecting the active provider, plus the ordered
fallback chain used by the agent for provider failover.

Fallback configuration (config.json):

    "providers_fallback": ["gemini", "omniroute", "custom"]

- The active provider (active_provider/active_model) is always tried first.
- Every id listed afterwards is appended (deduplicated, only when the id
  exists in "providers") as a failover target.
- Unknown/missing ids are ignored, so the list is safe to hand-edit.
"""

import os
from typing import Optional
from rex.config import load_config, normalize_config
from rex.providers.base import BaseLLMProvider
from rex.providers.gemini import GeminiProvider
from rex.providers.router import OpenAIRouterProvider


def build_provider(provider_id: str, model_name: str, cfg: Optional[dict] = None) -> BaseLLMProvider:
    """Instantiate one provider by id. Raises when the provider is unknown."""
    if cfg is None:
        cfg = normalize_config(load_config())
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


def get_fallback_chain(cfg: Optional[dict] = None) -> list:
    """
    Ordered (provider_id, model_name) chain: active provider first, then the
    ids from config "providers_fallback" (deduplicated, existing only).
    """
    if cfg is None:
        cfg = normalize_config(load_config())
    providers = cfg.get("providers", {})
    chain = [(cfg.get("active_provider", "gemini"), cfg.get("active_model", ""))]
    for pid in cfg.get("providers_fallback") or []:
        if isinstance(pid, str) and pid in providers and pid != chain[0][0]:
            chain.append((pid, providers[pid].get("model", "")))
    return chain


def get_llm_provider_with_fallback(cfg: Optional[dict] = None):
    """Return (primary_provider, chain) for the agent's failover loop."""
    if cfg is None:
        cfg = normalize_config(load_config())
    chain = get_fallback_chain(cfg)
    primary_id, primary_model = chain[0]
    return build_provider(primary_id, primary_model, cfg), chain


def get_llm_provider() -> BaseLLMProvider:
    """
    Get the configured active provider (legacy single-provider entry point).
    """
    cfg = normalize_config(load_config())
    provider_id = cfg["active_provider"]
    model_name = cfg["active_model"]
    return build_provider(provider_id, model_name, cfg)
