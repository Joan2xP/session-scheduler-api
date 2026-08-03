import json
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Generator

from django.conf import settings
from django.db import close_old_connections

from .provider import get_provider, Message, ToolCall, StreamChunk
from .tools import get_all_tools, get_tool
from .prompts import get_system_prompt

logger = logging.getLogger(__name__)

MAX_ITERATIONS = getattr(settings, "AI_MAX_TOOL_ITERATIONS", 10)
TOOL_EXECUTION_TIMEOUT = getattr(settings, "AI_TOOL_EXECUTION_TIMEOUT", 45)
MAX_TOOL_CALLS_PER_TURN = getattr(settings, "AI_MAX_TOOL_CALLS_PER_TURN", 10)


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


def _execute_tool_safe(tool_call: ToolCall, user) -> dict:
    try:
        return execute_tool(tool_call, user)
    finally:
        close_old_connections()


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

        text_parts = []
        tool_calls = []

        for chunk in provider.chat_stream(conversation, tools, system_prompt):
            if chunk.type == "text":
                text_parts.append(chunk.content)
                yield _sse_event({"type": "text", "content": chunk.content})
            elif chunk.type == "tool_call":
                tool_calls.append(chunk.tool_call)

        if not tool_calls:
            if text_parts:
                conversation.append(Message(role="assistant", content="".join(text_parts)))
            yield _sse_event({"type": "done"})
            return

        if len(tool_calls) > MAX_TOOL_CALLS_PER_TURN:
            yield _sse_event({
                "type": "error",
                "content": f"Too many tool calls in one turn: {len(tool_calls)} (max {MAX_TOOL_CALLS_PER_TURN})",
            })
            yield _sse_event({"type": "done"})
            return

        yield _sse_event({"type": "tool_call_start", "count": len(tool_calls)})

        executor = ThreadPoolExecutor(max_workers=min(len(tool_calls), 4))
        try:
            futures = [
                executor.submit(_execute_tool_safe, tc, user)
                for tc in tool_calls
            ]
            results = []
            for f, tc in zip(futures, tool_calls):
                try:
                    results.append(f.result(timeout=TOOL_EXECUTION_TIMEOUT))
                except FutureTimeoutError:
                    results.append({"error": f"Tool {tc.name} timed out after {TOOL_EXECUTION_TIMEOUT}s"})
        finally:
            executor.shutdown(wait=False)

        conversation.append(Message(
            role="assistant",
            content="".join(text_parts) if text_parts else None,
            tool_calls=tool_calls,
        ))

        for tc, result in zip(tool_calls, results):
            yield _sse_event({
                "type": "tool_result",
                "name": tc.name,
                "result": result,
            })

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
