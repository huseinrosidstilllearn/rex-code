"""
rex.providers.base
Abstract base class for all LLM providers.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional


class StreamEvent:
    def __init__(self, kind: str, data: Any):
        self.kind = kind
        self.data = data

class LLMResponse:
    def __init__(self, content: Optional[str] = None, tool_calls: Optional[List[Dict[str, Any]]] = None):
        self.content = content or ""
        self.tool_calls = tool_calls or []

    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0

class BaseLLMProvider(ABC):
    @abstractmethod
    def chat(self, messages: List[Dict[str, Any]], system_prompt: str, tools: Optional[List[Dict[str, Any]]] = None) -> LLMResponse:
        """
        Send messages and return response with optional tool calls.
        """
        pass
