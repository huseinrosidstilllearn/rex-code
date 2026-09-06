"""
rex.providers.router
Universal OpenAI-Compatible Router (supports 9router, OmniRoute, OpenRouter, Ollama, and custom base URLs).
Supports API Key and OAuth/Bearer tokens.
"""

import json
import urllib.request
import urllib.error
import time
from typing import List, Dict, Any, Optional
from rex.providers.base import BaseLLMProvider, LLMResponse, StreamEvent, Usage
from rex.retry import compute_backoff, parse_usage

class OpenAIRouterProvider(BaseLLMProvider):
    def __init__(self, base_url: str, api_key: Optional[str] = None, model: str = "gpt-4o-mini", bearer_token: Optional[str] = None, timeout_sec: int = 120, retry_attempts: int = 3, retry_backoff_sec: float = 1):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or ""
        self.bearer_token = bearer_token
        self.model = model
        self.timeout_sec = timeout_sec
        self.retry_attempts = max(1, int(retry_attempts))
        self.retry_backoff_sec = max(0, float(retry_backoff_sec))

    def _open(self, request):
        for attempt in range(self.retry_attempts):
            try:
                return urllib.request.urlopen(request, timeout=self.timeout_sec)
            except urllib.error.HTTPError as error:
                if error.code != 429 and error.code < 500:
                    raise
                if attempt == self.retry_attempts - 1:
                    raise
                time.sleep(compute_backoff(attempt, self.retry_backoff_sec))

    def chat(self, messages: List[Dict[str, Any]], system_prompt: str, tools: Optional[List[Dict[str, Any]]] = None) -> LLMResponse:
        url = f"{self.base_url}/chat/completions"

        # Transform messages: prepend system prompt as first message
        formatted_msgs = [{"role": "system", "content": system_prompt}]
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")
            if role in ["user", "system"]:
                formatted_msgs.append({"role": role, "content": str(content)})
            elif role == "assistant":
                item: Dict[str, Any] = {"role": "assistant", "content": str(content) if content else ""}
                if "tool_calls" in msg:
                    # format OpenAI tool calls
                    tc_list = []
                    for i, tc in enumerate(msg["tool_calls"]):
                        tc_list.append({
                            "id": tc.get("id", f"call_{i}"),
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc["args"])
                            }
                        })
                    item["tool_calls"] = tc_list
                formatted_msgs.append(item)
            elif role == "tool":
                formatted_msgs.append({
                    "role": "tool",
                    "name": msg.get("name", ""),
                    "tool_call_id": msg.get("tool_call_id", "call_0"),
                    "content": str(content)
                })

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": formatted_msgs,
            "temperature": 0.3
        }

        if tools:
            payload["tools"] = [{
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["parameters"]
                }
            } for t in tools]
            payload["tool_choice"] = "auto"

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "RexCode/1.0"
        }

        # Auth: Bearer Token or API Key
        token = self.bearer_token or self.api_key
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            req_data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=req_data, headers=headers)
            with self._open(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            choices = data.get("choices", [])
            if not choices:
                return LLMResponse(content="(Tidak ada respon dari model)")

            message = choices[0].get("message", {})
            content = message.get("content") or ""
            raw_tool_calls = message.get("tool_calls", [])

            tool_calls = []
            for tc in raw_tool_calls:
                func = tc.get("function", {})
                args = {}
                try:
                    args = json.loads(func.get("arguments", "{}"))
                except Exception:
                    pass
                tool_calls.append({
                    "id": tc.get("id"),
                    "name": func.get("name"),
                    "args": args
                })

            return LLMResponse(content=content, tool_calls=tool_calls, usage=Usage.from_dict(parse_usage(data)))

        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                message = "Autentikasi provider gagal. Periksa API key."
            elif e.code == 429:
                message = "Kuota provider habis atau terlalu banyak permintaan. Coba lagi nanti."
            else:
                message = f"Provider mengembalikan HTTP {e.code}."
            return LLMResponse(content=message)
        except Exception:
            return LLMResponse(content="Koneksi ke provider gagal. Periksa base URL dan jaringan.")

    def chat_stream(self, messages: List[Dict[str, Any]], system_prompt: str, tools: Optional[List[Dict[str, Any]]] = None):
        """Yield text deltas, then one final LLMResponse from an OpenAI SSE stream."""
        url = f"{self.base_url}/chat/completions"
        formatted = [{"role": "system", "content": system_prompt}]
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")
            if role in ("user", "system"):
                formatted.append({"role": role, "content": str(content)})
            elif role == "assistant":
                item = {"role": role, "content": str(content) if content else ""}
                if msg.get("tool_calls"):
                    item["tool_calls"] = [{
                        "id": tc.get("id", f"call_{i}"), "type": "function",
                        "function": {"name": tc["name"], "arguments": json.dumps(tc.get("args", {}))},
                    } for i, tc in enumerate(msg["tool_calls"])]
                formatted.append(item)
            elif role == "tool":
                formatted.append({"role": "tool", "name": msg.get("name", ""),
                                  "tool_call_id": msg.get("tool_call_id", "call_0"), "content": str(content)})

        payload = {"model": self.model, "messages": formatted, "temperature": 0.3, "stream": True}
        if tools:
            payload["tools"] = [{"type": "function", "function": {
                "name": tool["name"], "description": tool["description"], "parameters": tool["parameters"]
            }} for tool in tools]
            payload["tool_choice"] = "auto"
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream", "User-Agent": "RexCode/1.0"}
        token = self.bearer_token or self.api_key
        if token:
            headers["Authorization"] = f"Bearer {token}"

        emitted = False
        stream_usage = None
        try:
            request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
            with self._open(request) as response:
                if "text/event-stream" not in response.headers.get("Content-Type", ""):
                    data = json.loads(response.read().decode("utf-8"))
                    message = (data.get("choices") or [{}])[0].get("message", {})
                    final = self._response_from_message(message)
                    final.usage = Usage.from_dict(parse_usage(data))
                    if final.content:
                        yield StreamEvent("text", final.content)
                    yield StreamEvent("final", final)
                    return

                content_parts = []
                calls = {}
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                    if not line.startswith("data:"):
                        continue
                    value = line[5:].strip()
                    if value == "[DONE]":
                        break
                    chunk = json.loads(value)
                    if chunk.get("usage"):
                        stream_usage = parse_usage(chunk)
                    delta = (chunk.get("choices") or [{}])[0].get("delta", {})
                    text = delta.get("content") or ""
                    if text:
                        emitted = True
                        content_parts.append(text)
                        yield StreamEvent("text", text)
                    for fragment in delta.get("tool_calls") or []:
                        index = fragment.get("index", 0)
                        call = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                        call["id"] += fragment.get("id") or ""
                        function = fragment.get("function") or {}
                        call["name"] += function.get("name") or ""
                        call["arguments"] += function.get("arguments") or ""
                tool_calls = []
                for call in calls.values():
                    try:
                        args = json.loads(call["arguments"] or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    tool_calls.append({"id": call["id"] or None, "name": call["name"], "args": args})
                yield StreamEvent("final", LLMResponse("".join(content_parts), tool_calls, usage=Usage.from_dict(stream_usage)))
        except Exception:
            if emitted:
                raise
            final = self.chat(messages, system_prompt, tools)
            if final.content:
                yield StreamEvent("text", final.content)
            yield StreamEvent("final", final)

    @staticmethod
    def _response_from_message(message: Dict[str, Any]) -> LLMResponse:
        tool_calls = []
        for raw in message.get("tool_calls") or []:
            function = raw.get("function") or {}
            try:
                args = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append({"id": raw.get("id"), "name": function.get("name"), "args": args})
        return LLMResponse(message.get("content") or "", tool_calls)
