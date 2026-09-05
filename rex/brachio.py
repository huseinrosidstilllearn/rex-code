"""
rex.brachio
Sub-agent module for delegating complex tasks.
Brachio breaks a high-level task into steps and executes it using RexAgent.
"""

from typing import Optional
from rex.config import load_config, get_active_mode, set_active_mode
from rex.core import RexAgent


class BrachioAgent:
    """Lightweight sub-agent that runs a single task autonomously."""

    def __init__(self, max_depth: int = 1):
        self._max_depth = max_depth
        self._depth = 0
        self._prev_mode: Optional[str] = None

    def run(self, task: str, context: str = "") -> str:
        if self._depth >= self._max_depth:
            return "DIBLOKIR: delegasi rekursif tidak diizinkan."
        self._depth += 1
        self._prev_mode = get_active_mode()
        set_active_mode("build")
        try:
            agent = RexAgent()
            prompt = (
                "You are Brachio, a sub-agent of Rex Code.\n"
                "Execute the following task using available tools.\n"
                "Always report the final outcome clearly.\n\n"
                f"Context:\n{context}\n\nTask:\n{task}"
            )
            return agent.run(prompt)
        finally:
            set_active_mode(self._prev_mode or "plan")
            self._depth -= 1
