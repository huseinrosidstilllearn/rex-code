"""
rex.providers.gemini
Native Google Gemini Provider using the official google-genai SDK.
Handles thought signatures and automatic tool execution natively.
"""

import inspect
import os
from typing import List, Dict, Any, Optional, Callable
from google import genai
from google.genai import types
from dotenv import load_dotenv
from rex.config import ENV_FILE, load_config
from rex.plugins import effective_tool_registry
from rex.providers.base import BaseLLMProvider, LLMResponse, StreamEvent

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

class GeminiProvider(BaseLLMProvider):
    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-flash-latest"):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self.model = model
        self.client = genai.Client(api_key=self.api_key)
        self.chat_session = None

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

        self.chat_session = self.client.chats.create(
            model=self.model,
            history=history or [],
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                tools=tools,
                temperature=0.2
            )
        )

    def chat_simple(self, message: str, system_prompt: str, on_tool_callback: Optional[Callable[[str, dict], None]] = None, history: Optional[List[Dict[str, Any]]] = None) -> str:
        """Run one Gemini chat turn with automatic tools."""
        self._ensure_session(system_prompt, on_tool_callback, history)

        # Retry on rate limit spikes
        import time
        for attempt in range(3):
            try:
                resp = self.chat_session.send_message(message)
                return resp.text or ""
            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    time.sleep(3 * (attempt + 1))
                    continue
                raise e
        return "(Batas permintaan rate-limit tercapai, silakan tunggu beberapa detik dan coba lagi)"

    def chat_simple_stream(self, message: str, system_prompt: str, on_tool_callback: Optional[Callable[[str, dict], None]] = None, history: Optional[List[Dict[str, Any]]] = None):
        """Yield Gemini text deltas, then one final LLMResponse."""
        self._ensure_session(system_prompt, on_tool_callback, history)
        import time
        for attempt in range(3):
            emitted = False
            parts = []
            try:
                for chunk in self.chat_session.send_message_stream(message):
                    text = chunk.text or ""
                    if text:
                        emitted = True
                        parts.append(text)
                        yield StreamEvent("text", text)
                yield StreamEvent("final", LLMResponse("".join(parts)))
                return
            except Exception as error:
                if emitted:
                    raise
                if "429" in str(error) or "RESOURCE_EXHAUSTED" in str(error):
                    time.sleep(3 * (attempt + 1))
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
        res_text = self.chat_simple(last_msg, system_prompt)
        return LLMResponse(content=res_text, tool_calls=[])
