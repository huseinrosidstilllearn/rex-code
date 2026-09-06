"""
rex.core
The ReAct autonomous execution engine of Rex Code.
Manages Plan & Build modes, tool executions, and self-healing auto-debug loops.
Includes provider failover: when the active provider fails mid-round, the
agent transparently retries the round on the next provider in the configured
fallback chain (config "providers_fallback", ordered provider ids).
"""

from typing import List, Dict, Any, Callable, Optional
import threading
from rex.config import load_config, get_active_mode, set_active_mode
from rex.prompts import PLAN_MODE_PROMPT, BUILD_MODE_PROMPT
from rex.tools import TOOL_DEFINITIONS, TOOL_REGISTRY
from rex.plugins import effective_tool_definitions, effective_tool_registry
from rex.providers.manager import get_llm_provider_with_fallback, build_provider
from rex.providers.gemini import GeminiProvider
from rex.providers.base import LLMResponse
from rex.anti_slop import clean_slop
from rex.sessions import session_store
from rex.logging_setup import log
from rex.context_inject import build_context_prefix
from rex.compaction import maybe_compact
from rex.vision import extract_references, build_gemini_message
from rex import todos as _todos
from rex.usage import UsageMeter

class StepEvent:
    def __init__(self, event_type: str, data: Any):
        self.event_type = event_type  # 'thought', 'tool_call', 'tool_result', 'error', 'done', 'mode_switch'
        self.data = data

class RexAgent:
    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id
        cfg = load_config()
        limit = cfg.get("max_history_messages", 40)
        self.messages: List[Dict[str, Any]] = (
            session_store.model_messages(session_id, limit) if session_id else []
        )
        self.provider = get_llm_provider_with_fallback()[0]
        self._provider_chain: Optional[List[tuple]] = None
        self._chain_index = 0
        self._abort = threading.Event()
        # Cumulative token usage + cost estimate for this agent instance.
        self.usage = UsageMeter()

    def abort(self):
        """Request cooperative cancellation before next tool or provider step."""
        self._abort.set()

    def _remember(self, message: Dict[str, Any]):
        if self.session_id:
            message = session_store.append(self.session_id, message)
        self.messages.append(message)

    def _remember_user_once(self, user_input: str) -> None:
        """Persist the user message once per run, even across provider failover
        retries (the failed attempt already wrote it to the session store)."""
        if getattr(self, "_user_persisted_this_run", False):
            self.messages.append({"role": "user", "content": user_input})
        else:
            self._remember({"role": "user", "content": user_input})
            self._user_persisted_this_run = True

    @property
    def total_usage(self) -> Dict[str, int]:
        """Backward-compatible cumulative totals (see rex.usage.UsageMeter)."""
        return self.usage.totals()

    def _accumulate_usage(self, usage) -> None:
        """Add one response's usage into the meter (None-safe)."""
        self.usage.accumulate(usage)
        # Persist into the session record for /stats (never raises).
        if self.session_id:
            session_store.add_usage(self.session_id, usage)

    def _advance_provider(self) -> bool:
        """Move to the next provider in the fallback chain. False = exhausted."""
        chain = getattr(self, "_provider_chain", None)
        if not chain:
            return False
        while self._chain_index + 1 < len(chain):
            self._chain_index += 1
            provider_id, model_name = chain[self._chain_index]
            try:
                self.provider = build_provider(provider_id, model_name)
                log.warning("provider_failover to=%s model=%s", provider_id, model_name)
                return True
            except Exception as exc:
                log.warning("provider_failover build failed provider=%s error=%s", provider_id, exc)
                continue
        return False

    def _trim_history(self, limit: int):
        self.messages = self.messages[-max(1, int(limit)):]
        while self.messages and (
            self.messages[0].get("role") == "tool"
            or self.messages[0].get("tool_calls")
        ):
            self.messages.pop(0)

    def reset(self):
        self.messages = []
        self.usage.reset()
        if isinstance(self.provider, GeminiProvider):
            self.provider.reset_session()

    def set_mode(self, mode: str):
        set_active_mode(mode)
        # Reset session to switch system prompt cleanly
        if isinstance(self.provider, GeminiProvider):
            self.provider.reset_session()

    def get_mode(self) -> str:
        return get_active_mode()

    # ────────────────────────────────────────────────────────────────
    # Provider rounds (one full agent round per provider family)
    # ────────────────────────────────────────────────────────────────

    def _gemini_round(self, user_input: str, system_prompt: str, cfg: dict,
                      on_step: Optional[Callable[[StepEvent], None]]) -> str:
        """One round on the Gemini provider (native tool loop). Raises on failure."""
        def on_tool(name: str, args: dict):
            if on_step:
                on_step(StepEvent("tool_call", {"name": name, "args": args}))

        history = []
        for message in self.messages:
            if message.get("role") in ("user", "assistant"):
                role = "model" if message["role"] == "assistant" else "user"
                history.append({"role": role, "parts": [{"text": str(message.get("content", ""))}]})

        # Attach vision parts when @image references were present.
        payload = build_gemini_message(user_input, getattr(self, "_attachments", []))

        if cfg.get("stream_enabled", True):
            final_response = ""
            for event in self.provider.chat_simple_stream(
                message=payload, system_prompt=system_prompt,
                on_tool_callback=on_tool, history=history,
            ):
                if self._abort.is_set():
                    final_response = "Proses dibatalkan oleh pengguna."
                    break
                if event.kind == "text" and on_step:
                    on_step(StepEvent("stream_delta", event.data))
                elif event.kind == "final":
                    final_response = event.data.content
                    self._accumulate_usage(getattr(event.data, "usage", None))
        else:
            final_llm_response = self.provider.chat_simple_with_usage(
                message=payload, system_prompt=system_prompt,
                on_tool_callback=on_tool, history=history,
            )
            final_response = final_llm_response.content
            self._accumulate_usage(final_llm_response.usage)

        if cfg.get("anti_slop_enabled", True):
            final_response, _ = clean_slop(final_response)
        self._remember_user_once(user_input)
        self._remember({"role": "assistant", "content": final_response})
        return final_response

    def _router_round(self, user_input: str, system_prompt: str, cfg: dict,
                      on_step: Optional[Callable[[StepEvent], None]]) -> str:
        """One round on the universal router provider (ReAct tool loop). Raises on failure."""
        tools_definitions = effective_tool_definitions()
        tools_registry = effective_tool_registry()
        max_steps = cfg.get("max_steps", 20)
        self._remember_user_once(user_input)
        current_step = 0
        final_response = ""

        while current_step < max_steps:
            if self._abort.is_set():
                final_response = "Proses dibatalkan oleh pengguna."
                self._remember({"role": "assistant", "content": final_response})
                break
            current_step += 1
            if cfg.get("stream_enabled", True) and hasattr(self.provider, "chat_stream"):
                resp = None
                for event in self.provider.chat_stream(
                    messages=self.messages, system_prompt=system_prompt, tools=tools_definitions
                ):
                    if self._abort.is_set():
                        final_response = "Proses dibatalkan oleh pengguna."
                        resp = LLMResponse(content=final_response)
                        break
                    if event.kind == "text" and on_step:
                        on_step(StepEvent("stream_delta", event.data))
                    elif event.kind == "final":
                        resp = event.data
                        self._accumulate_usage(getattr(event.data, "usage", None))
                if not resp:
                    raise RuntimeError("Provider stream selesai tanpa respons final")
            else:
                resp = self.provider.chat(
                    messages=self.messages,
                    system_prompt=system_prompt,
                    tools=tools_definitions
                )
                self._accumulate_usage(getattr(resp, "usage", None))

            if resp.has_tool_calls():
                assistant_message = {
                    "role": "assistant",
                    "content": resp.content,
                    "tool_calls": resp.tool_calls
                }
                self._remember(assistant_message)

                if resp.content and on_step:
                    on_step(StepEvent("thought", resp.content))

                for tc in resp.tool_calls:
                    if self._abort.is_set():
                        final_response = "Proses dibatalkan oleh pengguna."
                        self._remember({"role": "assistant", "content": final_response})
                        break
                    func_name = tc.get("name")
                    args = tc.get("args", {})

                    if on_step:
                        on_step(StepEvent("tool_call", {"name": func_name, "args": args}))
                    log.info("tool_call name=%s session=%s", func_name, self.session_id or "none")

                    if func_name in tools_registry:
                        try:
                            result = tools_registry[func_name](**args)
                        except Exception as e:
                            result = f"Exception saat eksekusi {func_name}: {str(e)}"
                    else:
                        result = f"Error: Tool '{func_name}' tidak terdaftar."

                    if on_step:
                        on_step(StepEvent("tool_result", {"name": func_name, "result": result}))

                    self._remember({
                        "role": "tool",
                        "name": func_name,
                        "tool_call_id": tc.get("id") or f"call_{func_name}",
                        "content": str(result)
                    })
                if final_response:
                    break
                continue
            else:
                final_response = resp.content
                if cfg.get("anti_slop_enabled", True):
                    final_response, _ = clean_slop(final_response)
                self._remember({
                    "role": "assistant",
                    "content": final_response
                })
                break

        if not final_response:
            final_response = f"Proses dihentikan setelah mencapai batas {max_steps} langkah. Persempit tugas atau naikkan max_steps."
            self._remember({"role": "assistant", "content": final_response})
        return final_response

    def run(self, user_input: str, on_step: Optional[Callable[[StepEvent], None]] = None) -> str:
        """
        Run one round of autonomous execution with provider failover.
        """
        cfg = load_config()
        self._abort.clear()
        self._user_persisted_this_run = False
        self.usage.refresh_config()
        # Scope the agent todo board to this session for todo_write, and
        # surface every board update as a todo_update StepEvent (works for
        # both provider loops — the tools layer fires the write listener).
        _todos.set_current_session(self.session_id)
        if on_step:
            _todos.set_write_listener(
                lambda sid, board: on_step(StepEvent("todo_update", {
                    "todos": board,
                    "summary": _todos.summary(board),
                    "session": sid or self.session_id,
                }))
            )
        # Multimodal + @file injection (shared by CLI/TUI/headless).
        clean_input, attachments, _vision_notes = extract_references(user_input)
        self._attachments = attachments
        # Compaction first (LLM summary), then safe trim as backstop.
        try:
            compacted, did_compact = maybe_compact(self.messages)
            if did_compact:
                self.messages = compacted
                log.info("context_compacted messages=%d", len(self.messages))
        except Exception:
            pass
        self._trim_history(cfg.get("max_history_messages", 40))
        mode = get_active_mode()
        system_prompt = PLAN_MODE_PROMPT if mode == "plan" else BUILD_MODE_PROMPT
        system_prompt = system_prompt + build_context_prefix(mode)

        # Fresh chain per run so /model switches apply on the next input.
        self.provider, self._provider_chain = get_llm_provider_with_fallback()
        self._chain_index = 0

        final_response = ""
        attempts = max(1, len(self._provider_chain or [None]))
        for _ in range(attempts):
            snapshot = list(self.messages)
            try:
                if isinstance(self.provider, GeminiProvider):
                    final_response = self._gemini_round(clean_input, system_prompt, cfg, on_step)
                else:
                    final_response = self._router_round(clean_input, system_prompt, cfg, on_step)
                break
            except Exception as error:
                # Discard the partial round (half-remembered tool messages),
                # then retry the whole round on the next provider in the chain.
                self.messages = snapshot
                log.error("provider_error type=%s session=%s", type(error).__name__, self.session_id or "none")
                if not self._advance_provider():
                    final_response = "Provider gagal memproses permintaan. Periksa konfigurasi dan logs/rex.log."
                    break

        if on_step:
            on_step(StepEvent("done", final_response))

        _todos.set_current_session(None)  # run() over: clear the board scope
        self._trim_history(cfg.get("max_history_messages", 40))

        return final_response
