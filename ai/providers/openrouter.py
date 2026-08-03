import json
import logging
from typing import Generator

from openai import OpenAI
from django.conf import settings

from ..provider import AIProvider, Message, ToolDefinition, StreamChunk, ToolCall

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterProvider(AIProvider):
    def __init__(self):
        self.api_key = getattr(settings, "AI_PROVIDER_API_KEY", "")
        self.model_name = getattr(settings, "AI_MODEL", "google/gemini-2.5-flash")
        self._client = None

    @property
    def client(self):
        if self._client is None:
            if not self.api_key:
                raise ValueError(
                    "AI_PROVIDER_API_KEY is not set. "
                    "Set it via environment variable or Django settings."
                )
            self._client = OpenAI(
                base_url=OPENROUTER_BASE_URL,
                api_key=self.api_key,
            )
        return self._client

    def get_tool_definitions(self, tools: list[ToolDefinition]) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in tools
        ]

    def _convert_messages(self, messages: list[Message], system_prompt: str) -> list[dict]:
        result = [{"role": "system", "content": system_prompt}]

        for msg in messages:
            if msg.role == "user":
                result.append({"role": "user", "content": msg.content or ""})
            elif msg.role == "assistant":
                entry = {"role": "assistant", "content": msg.content}
                if msg.tool_calls:
                    entry["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                        for tc in msg.tool_calls
                    ]
                result.append(entry)
            elif msg.role == "tool":
                for tc_result in msg.tool_calls:
                    result.append({
                        "role": "tool",
                        "tool_call_id": tc_result["id"],
                        "content": json.dumps(tc_result["response"]),
                    })

        return result

    def chat_stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        system_prompt: str,
    ) -> Generator[StreamChunk, None, None]:
        tool_defs = self.get_tool_definitions(tools)
        converted = self._convert_messages(messages, system_prompt)

        stream = self.client.chat.completions.create(
            model=self.model_name,
            messages=converted,
            tools=tool_defs,
            stream=True,
        )

        tool_calls_acc = {}

        for chunk in stream:
            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta

            if delta.content:
                yield StreamChunk(type="text", content=delta.content)

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {"id": "", "name": "", "arguments": ""}
                    if tc.id:
                        tool_calls_acc[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tool_calls_acc[idx]["name"] = tc.function.name
                        if tc.function.arguments:
                            tool_calls_acc[idx]["arguments"] += tc.function.arguments

        for idx in sorted(tool_calls_acc):
            tc = tool_calls_acc[idx]
            yield StreamChunk(
                type="tool_call",
                tool_call=ToolCall(
                    id=tc["id"],
                    name=tc["name"],
                    arguments=json.loads(tc["arguments"]) if tc["arguments"] else {},
                ),
            )
