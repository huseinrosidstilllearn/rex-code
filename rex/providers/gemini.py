"""
rex.providers.gemini
Native Google Gemini Provider using the official google-genai SDK.
Handles thought signatures and automatic tool execution natively.
"""

import os
from typing import List, Dict, Any, Optional, Callable
from google import genai
from google.genai import types
from dotenv import load_dotenv
from rex.config import ENV_FILE, load_config
from rex.providers.base import BaseLLMProvider, LLMResponse, StreamEvent
from rex.tools import delete_file, edit_file, list_dir, read_file, run_command, search_content, search_files, write_file

load_dotenv(ENV_FILE)

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

        def limited(result: str) -> str:
            result = str(result)
            return result if len(result) <= max_chars else result[:max_chars - 14] + "\n...[dipotong]"

        # Wrap tools to notify callback if provided
        def wrapped_write_file(path: str, content: str) -> str:
            if on_tool_callback:
                on_tool_callback("write_file", {"path": path, "content_len": len(content)})
            return limited(write_file(path, content))

        def wrapped_read_file(path: str) -> str:
            if on_tool_callback:
                on_tool_callback("read_file", {"path": path})
            return limited(read_file(path))

        def wrapped_edit_file(path: str, target_content: str, replacement_content: str) -> str:
            if on_tool_callback:
                on_tool_callback("edit_file", {"path": path})
            return limited(edit_file(path, target_content, replacement_content))

        def wrapped_list_dir(path: str = ".") -> str:
            if on_tool_callback:
                on_tool_callback("list_dir", {"path": path})
            return limited(list_dir(path))

        def wrapped_search_files(query: str, path: str = ".") -> str:
            if on_tool_callback:
                on_tool_callback("search_files", {"query": query, "path": path})
            return limited(search_files(query, path))

        def wrapped_run_command(command: str) -> str:
            if on_tool_callback:
                on_tool_callback("run_command", {"command": command})
            return limited(run_command(command))

        def wrapped_search_content(query: str, path: str = ".") -> str:
            if on_tool_callback:
                on_tool_callback("search_content", {"query": query, "path": path})
            return limited(search_content(query, path))

        def wrapped_delete_file(path: str) -> str:
            if on_tool_callback:
                on_tool_callback("delete_file", {"path": path})
            return limited(delete_file(path))

        tools = [
            wrapped_read_file,
            wrapped_write_file,
            wrapped_edit_file,
            wrapped_list_dir,
            wrapped_search_files,
            wrapped_search_content,
            wrapped_delete_file,
            wrapped_run_command
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
