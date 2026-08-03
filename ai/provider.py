import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Generator, Optional

from django.conf import settings

logger = logging.getLogger(__name__)


@dataclass
class Message:
    role: str
    content: Optional[str] = None
    tool_calls: list = field(default_factory=list)
    tool_call_id: Optional[str] = None


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class StreamChunk:
    type: str
    content: Optional[str] = None
    tool_call: Optional[ToolCall] = None
    tool_result: Optional[dict] = None


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict
    execute: callable


class AIProvider(ABC):
    @abstractmethod
    def chat_stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        system_prompt: str,
    ) -> Generator[StreamChunk, None, None]:
        pass

    @abstractmethod
    def get_tool_definitions(self, tools: list[ToolDefinition]) -> Any:
        pass


def get_provider() -> AIProvider:
    provider_name = getattr(settings, "AI_PROVIDER", "openrouter")

    if provider_name == "openrouter":
        from .providers.openrouter import OpenRouterProvider
        return OpenRouterProvider()
    else:
        raise ValueError(f"Unknown AI provider: {provider_name}")
