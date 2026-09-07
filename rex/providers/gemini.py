"""
rex.providers.gemini
Native Google Gemini Provider using the official google-genai SDK.
Handles thought signatures and automatic tool execution natively.
"""

import inspect
import os
import time
from typing import List, Dict, Any, Optional, Callable
from google import genai
from google.genai import types
from dotenv import load_dotenv
from rex.config import ENV_FILE, load_config
from rex.plugins import effective_tool_registry
from rex.providers.base import BaseLLMProvider, LLMResponse, StreamEvent, Usage
from rex.retry import compute_backoff

load_dotenv(ENV_FILE)

# Map JSON schema types to Python annotations used to build the tool signature.
_JSON_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _schema_for_callable(func: Callable) -> dict:
    """Best-effort JSON schema derived from a callable's annotations."""
    properties = {}
    required = []
    for name, parameter in inspect.signature(func).parameters.items():
        annotation = parameter.annotation
        if annotation is inspect.Parameter.empty:
            json_type = "string"
        elif annotation is int:
            json_type = "integer"
        elif annotation is float:
            json_type = "number"
        elif annotation is bool:
            json_type = "boolean"
        elif annotation in (list, List):
            json_type = "array"
        else:
            json_type = "string"
        properties[name] = {"type": json_type, "description": name}
        if parameter.default is inspect.Parameter.empty:
            required.append(name)
    return {"type": "object", "properties": properties, "required": required}


def _args_to_dict(signature: inspect.Signature, args) -> dict:
    """Map positional args onto parameter names using the tool signature."""
    return {pname: value for (pname, _), value in zip(signature.parameters.items(), args)}


def _build_wrapped_tool(name: str, func: Callable, on_tool_callback, max_chars: int) -> Callable:
    """
    Wrap a tool handler so the Gemini SDK sees a proper typed signature,
    the callback is notified, and results stay within the output budget.
    """
    schema = _schema_for_callable(func)
    required = set(schema.get("required") or [])
    parameters = [
        inspect.Parameter(
            pname,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            annotation=_JSON_TYPE_MAP.get((pdef or {}).get("type"), str),
            default=inspect.Parameter.empty if pname in required else None,
        )
        for pname, pdef in schema.get("properties", {}).items()
    ]
    signature = inspect.Signature(parameters)

    def wrapped(*args, **kwargs):
        if on_tool_callback:
            callback_args = dict(zip(signature.parameters, args)) | dict(kwargs)
            on_tool_callback(name, {
                key: (value[:500] + f"... ({len(value)} chars)") if isinstance(value, str) and len(value) > 500 else value
                for key, value in callback_args.items()
            })
        # Wasted-repeat guard: identical calls (name+args) executed several
        # times in a row get replaced by a strategy-change warning instead
        # of running the (identical) tool again.
        from rex.agentguard import active_guard
        guard = active_guard()
        guard_warning = None
        if guard is not None:
            try:
                guard_warning = guard.observe(name, {**_args_to_dict(signature, args), **dict(kwargs)})
            except Exception:
                guard_warning = None
        if guard_warning:
            return guard_warning
        result = str(func(*args, **kwargs))
        if len(result) > max_chars:
            result = result[: max(0, max_chars - 14)] + "\n...[dipotong]"
        return result

    wrapped.__signature__ = signature
    wrapped.__name__ = name
    wrapped.__annotations__ = {
        pname: parameter.annotation
        for pname, parameter in signature.parameters.items()
        if parameter.annotation is not inspect.Parameter.empty
    }
    return wrapped


def _usage_from_gemini(response: Any) -> Optional[Usage]:
    """Extract token usage from a Gemini GenerateContentResponse."""
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return None
    prompt = getattr(meta, "prompt_token_count", None)
    completion = getattr(meta, "candidates_token_count", None)
    total = getattr(meta, "total_token_count", None)
    if prompt is None and completion is None and total is None:
        return None
    return Usage(prompt, completion, total)


class GeminiProvider(BaseLLMProvider):
    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-flash-latest"):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self.model = model
        # Lazy client: constructing genai.Client with an empty key raises
        # immediately, which used to crash RexAgent() on first run (no key
        # configured yet). Defer to first actual use with a friendly error.
        self._client = None
        self.chat_session = None

    @property
    def client(self):
        if self._client is None:
            if not self.api_key:
                raise RuntimeError(
                    "GEMINI_API_KEY belum diatur. Buka Settings (rex --web → "
                    "Settings → Provider) atau isi .env, lalu coba lagi."
                )
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def reset_session(self):
        self.chat_session = None

    def _ensure_session(self, system_prompt: str, on_tool_callback=None, history=None):
        if self.chat_session:
            return
        max_chars = max(100, int(load_config().get("terminal_output_max_chars", 8000)))

        # Wrap every registered tool (built-ins + plugins) generically so
        # plugin tools are exposed to Gemini without code changes.
        tools = [
            _build_wrapped_tool(name, func, on_tool_callback, max_chars)
            for name, func in effective_tool_registry().items()
        ]

        # Cap the native AFC tool loop at the configured agent step limit
        # (SDK default is only 10 remote calls, below Rex's max_steps).
        max_steps = max(1, int(load_config().get("max_steps", 25)))
        afc = types.AutomaticFunctionCallingConfig(maximum_remote_calls=max_steps)

        self.chat_session = self.client.chats.create(
            model=self.model,
            history=history or [],
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                tools=tools,
                automatic_function_calling=afc,
                temperature=0.2
            )
        )

    def chat_simple(self, message: str, system_prompt: str, on_tool_callback: Optional[Callable[[str, dict], None]] = None, history: Optional[List[Dict[str, Any]]] = None) -> str:
        """Run one Gemini chat turn with automatic tools."""
        return self.chat_simple_with_usage(message, system_prompt, on_tool_callback, history).content

    def chat_simple_with_usage(self, message: str, system_prompt: str, on_tool_callback: Optional[Callable[[str, dict], None]] = None, history: Optional[List[Dict[str, Any]]] = None) -> LLMResponse:
        """Run one Gemini chat turn, returning content plus token usage."""
        self._ensure_session(system_prompt, on_tool_callback, history)

        for attempt in range(4):
            try:
                resp = self.chat_session.send_message(message)
                return LLMResponse(resp.text or "", usage=_usage_from_gemini(resp))
            except Exception as e:
                err_str = str(e)
                transient = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "500" in err_str or "503" in err_str
                if transient and attempt < 3:
                    time.sleep(compute_backoff(attempt, 1.0))
                    continue
                raise e
        return LLMResponse("(Batas permintaan rate-limit tercapai, silakan tunggu beberapa detik dan coba lagi)")

    def chat_simple_stream(self, message: str, system_prompt: str, on_tool_callback: Optional[Callable[[str, dict], None]] = None, history: Optional[List[Dict[str, Any]]] = None):
        """Yield Gemini text deltas, then one final LLMResponse."""
        self._ensure_session(system_prompt, on_tool_callback, history)
        for attempt in range(4):
            emitted = False
            parts = []
            try:
                final_usage = None
                for chunk in self.chat_session.send_message_stream(message):
                    text = chunk.text or ""
                    chunk_usage = _usage_from_gemini(chunk)
                    if chunk_usage is not None:
                        final_usage = chunk_usage
                    if text:
                        emitted = True
                        parts.append(text)
                        yield StreamEvent("text", text)
                yield StreamEvent("final", LLMResponse("".join(parts), usage=final_usage))
                return
            except Exception as error:
                if emitted:
                    raise
                err_str = str(error)
                transient = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "500" in err_str or "503" in err_str
                if transient and attempt < 3:
                    time.sleep(compute_backoff(attempt, 1.0))
                    continue
                raise
        message = "(Batas permintaan rate-limit tercapai, silakan tunggu beberapa detik dan coba lagi)"
        yield StreamEvent("text", message)
        yield StreamEvent("final", LLMResponse(message))

    def chat(self, messages: List[Dict[str, Any]], system_prompt: str, tools: Optional[List[Dict[str, Any]]] = None) -> LLMResponse:
        """
        Fallback chat method conforming to BaseLLMProvider.
        """
        last_msg = messages[-1].get("content", "") if messages else ""
        return self.chat_simple_with_usage(last_msg, system_prompt)
