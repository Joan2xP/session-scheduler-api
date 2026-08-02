import json
import logging
from typing import Generator

from django.conf import settings

from .provider import get_provider, Message, ToolCall, StreamChunk
from .tools import get_all_tools, get_tool
from .prompts import get_system_prompt

logger = logging.getLogger(__name__)

MAX_ITERATIONS = getattr(settings, "AI_MAX_TOOL_ITERATIONS", 10)


class ChatError(Exception):
    pass


def execute_tool(tool_call: ToolCall, user) -> dict:
    tool = get_tool(tool_call.name)
    if not tool:
        return {"error": f"Unknown tool: {tool_call.name}"}

    try:
        result = tool.execute(tool_call.arguments, user)
        return result
    except Exception as e:
        logger.error(f"Tool execution error: {tool_call.name}: {str(e)}", exc_info=True)
        return {"error": str(e)}


def chat_stream(messages: list[dict], user) -> Generator[str, None, None]:
    provider = get_provider()
    tools = get_all_tools()
    system_prompt = get_system_prompt()

    conversation = [
        Message(role=m["role"], content=m.get("content"))
        for m in messages
    ]

    iteration = 0
    while iteration < MAX_ITERATIONS:
        iteration += 1

        text_content, tool_calls = provider.chat_with_tools(
            messages=conversation,
            tools=tools,
            system_prompt=system_prompt,
        )

        if text_content:
            yield _sse_event({"type": "text", "content": text_content})

        if not tool_calls:
            yield _sse_event({"type": "done"})
            return

        for tc in tool_calls:
            yield _sse_event({
                "type": "tool_call",
                "name": tc.name,
                "arguments": tc.arguments,
            })

            result = execute_tool(tc, user)

            yield _sse_event({
                "type": "tool_result",
                "name": tc.name,
                "result": result,
            })

            conversation.append(Message(
                role="assistant",
                tool_calls=[tc],
            ))
            conversation.append(Message(
                role="tool",
                tool_calls=[{
                    "id": tc.id,
                    "name": tc.name,
                    "response": result,
                }],
            ))

    yield _sse_event({"type": "error", "content": "Maximum tool call iterations reached"})
    yield _sse_event({"type": "done"})


def _sse_event(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"
