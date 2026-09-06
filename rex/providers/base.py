"""
rex.providers.base
Abstract base class for all LLM providers.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional


class StreamEvent:
    def __init__(self, kind: str, data: Any):
        self.kind = kind
        self.data = data


class Usage:
    """Token usage for one LLM response. Fields are None when unknown."""

    __slots__ = ("prompt_tokens", "completion_tokens", "total_tokens")

    def __init__(self, prompt_tokens: Optional[int] = None, completion_tokens: Optional[int] = None,
                 total_tokens: Optional[int] = None):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens

    def to_dict(self) -> Dict[str, Optional[int]]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> Optional["Usage"]:
        if not isinstance(data, dict):
            return None
        return cls(data.get("prompt_tokens"), data.get("completion_tokens"), data.get("total_tokens"))


class LLMResponse:
    def __init__(self, content: Optional[str] = None, tool_calls: Optional[List[Dict[str, Any]]] = None,
                 usage: Optional[Usage] = None):
        self.content = content or ""
        self.tool_calls = tool_calls or []
        self.usage = usage

    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


class BaseLLMProvider(ABC):
    @abstractmethod
    def chat(self, messages: List[Dict[str, Any]], system_prompt: str, tools: Optional[List[Dict[str, Any]]] = None) -> LLMResponse:
        """
        Send messages and return response with optional tool calls.
        """
        pass
