"""The PLAN step: call the LLM through LangChain.

LangGraph owns orchestration. LangChain owns provider-neutral chat-model
invocation and tool-call normalization.
"""

import json
import random
from typing import Any

import anthropic
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_openai import ChatOpenAI
import openai

import config
from models.types import ChatMessage, LLMRequest, LLMResponse, ToolCall
from prompts import TOOLS


class SimulatedOpenAIFailure(RuntimeError):
    pass


async def call_llm(req: LLMRequest) -> LLMResponse:
    try:
        _maybe_fail_openai_call()
        model = _chat_model().bind_tools(_langchain_tools())
        response = await model.ainvoke(
            _to_langchain_messages(req.messages),
            config={
                "run_name": "support-agent-plan",
                "tags": ["langgraph", "support-agent"],
                "metadata": {"provider": config.LLM_PROVIDER},
            },
        )
    except (
        anthropic.BadRequestError,
        anthropic.AuthenticationError,
        anthropic.PermissionDeniedError,
        anthropic.NotFoundError,
        openai.BadRequestError,
        openai.AuthenticationError,
        openai.PermissionDeniedError,
        openai.NotFoundError,
    ) as e:
        raise ValueError(f"LLM request rejected: {e}") from e

    if not isinstance(response, AIMessage):
        raise TypeError(
            f"LangChain returned unexpected message type: {type(response).__name__}"
        )

    return LLMResponse(
        message=ChatMessage(
            role="assistant",
            content=_message_text(response.content),
            tool_calls=_tool_calls(response.tool_calls),
        )
    )


def _maybe_fail_openai_call() -> None:
    if config.LLM_PROVIDER != "openai" or config.OPENAI_FAILURE_RATE <= 0:
        return
    if random.random() < config.OPENAI_FAILURE_RATE:
        raise SimulatedOpenAIFailure(
            f"Simulated OpenAI API failure "
            f"(OPENAI_FAILURE_RATE={config.OPENAI_FAILURE_RATE})"
        )


def _chat_model():
    if config.LLM_PROVIDER == "openai":
        return ChatOpenAI(
            model=config.OPENAI_MODEL,
            max_retries=0,
            timeout=30,
        )
    if config.LLM_PROVIDER == "anthropic":
        return ChatAnthropic(
            model=config.ANTHROPIC_MODEL,
            max_retries=0,
            timeout=30,
            max_tokens=2048,
        )
    raise ValueError(
        f"Unsupported LLM_PROVIDER '{config.LLM_PROVIDER}'. Use 'anthropic' or 'openai'."
    )


def _langchain_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],
        }
        for tool in TOOLS
    ]


def _to_langchain_messages(messages: list[ChatMessage]) -> list[BaseMessage]:
    converted: list[BaseMessage] = []
    for message in messages:
        if message.role == "system":
            converted.append(SystemMessage(content=message.content))
        elif message.role == "user":
            converted.append(HumanMessage(content=message.content))
        elif message.role == "assistant":
            converted.append(
                AIMessage(
                    content=message.content,
                    tool_calls=[
                        {"id": call.id, "name": call.name, "args": call.args}
                        for call in message.tool_calls
                    ],
                )
            )
        elif message.role == "tool":
            if not message.tool_call_id:
                raise ValueError("Tool messages must include tool_call_id")
            converted.append(
                ToolMessage(
                    content=message.content,
                    tool_call_id=message.tool_call_id,
                )
            )
    return converted


def _message_text(content: str | list[Any]) -> str:
    if isinstance(content, str):
        return content

    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            if block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif "text" in block:
                parts.append(str(block["text"]))
    return "".join(parts)


def _tool_calls(tool_calls: list[dict[str, Any]]) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for index, call in enumerate(tool_calls):
        args = call.get("args") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {"input": args}
        if not isinstance(args, dict):
            args = {"input": args}

        calls.append(
            ToolCall(
                id=str(call.get("id") or f"call_{index}"),
                name=str(call["name"]),
                args=args,
            )
        )
    return calls
