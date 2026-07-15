"""The PLAN step (slide 28, primitive 02): call the LLM as a Temporal Activity.

Two self-contained provider functions with the same signature — read the one
you care about and stop. `LLM_PROVIDER` picks one; the workflow never knows.

Retry philosophy (slide 31): the SDK's own retries are OFF (max_retries=0) so
Temporal owns ALL retries — every rate-limit or outage is visible as a retry
in workflow history. Requests the provider rejects outright (bad auth, bad
request) are marked non-retryable: retrying can't fix those.
"""

import json

import anthropic
import openai
from temporalio import activity
from temporalio.exceptions import ApplicationError

import config
from models.types import ChatMessage, LLMRequest, LLMResponse, ToolCall
from prompts import TOOLS


@activity.defn
async def call_llm(req: LLMRequest) -> LLMResponse: 
    if config.LLM_PROVIDER == "openai":
        return await _call_openai(req)
    return await _call_anthropic(req)


async def _call_anthropic(req: LLMRequest) -> LLMResponse:
    client = anthropic.AsyncAnthropic(max_retries=0)

    system = next((m.content for m in req.messages if m.role == "system"), "")
    messages: list[dict] = []
    for m in req.messages:
        if m.role == "system":
            continue
        if m.role == "user":
            messages.append({"role": "user", "content": m.content})
        elif m.role == "assistant":
            blocks: list[dict] = []
            if m.content:
                blocks.append({"type": "text", "text": m.content})
            for c in m.tool_calls:
                blocks.append({"type": "tool_use", "id": c.id, "name": c.name, "input": c.args})
            messages.append({"role": "assistant", "content": blocks})
        else:
            block = {"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content}
            last = messages[-1] if messages else None
            if (last and last["role"] == "user" and isinstance(last["content"], list)
                    and last["content"] and last["content"][-1].get("type") == "tool_result"):
                last["content"].append(block)
            else:
                messages.append({"role": "user", "content": [block]})

    try:
        resp = await client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=2048,
            system=system,
            tools=TOOLS,
            messages=messages,
        )
    except (anthropic.BadRequestError, anthropic.AuthenticationError,
            anthropic.PermissionDeniedError, anthropic.NotFoundError) as e:
        raise ApplicationError(f"LLM request rejected: {e}", non_retryable=True) from e

    text = "".join(b.text for b in resp.content if b.type == "text")
    calls = [ToolCall(id=b.id, name=b.name, args=b.input)
             for b in resp.content if b.type == "tool_use"]
    return LLMResponse(message=ChatMessage(role="assistant", content=text, tool_calls=calls))


async def _call_openai(req: LLMRequest) -> LLMResponse:
    client = openai.AsyncOpenAI(max_retries=0)

    input_items: list[dict] = []
    for m in req.messages:
        if m.role == "tool":
            input_items.append({"type": "function_call_output",
                                "call_id": m.tool_call_id, "output": m.content})
        elif m.role == "assistant" and m.provider_items:
            # Replay the exact output, including encrypted reasoning items,
            # so reasoning survives the next function-call round with store=False.
            input_items.extend(m.provider_items)
        else:
            if m.content:
                input_items.append({"role": m.role, "content": m.content})
            for c in m.tool_calls:
                input_items.append({"type": "function_call", "call_id": c.id,
                                    "name": c.name, "arguments": json.dumps(c.args)})

    tools = [{"type": "function", "name": t["name"],
              "description": t["description"], "parameters": t["input_schema"],
              "strict": False}
             for t in TOOLS]

    try:
        resp = await client.responses.create(
            model=config.OPENAI_MODEL,
            input=input_items,
            tools=tools,
            store=False,
            include=["reasoning.encrypted_content"],
        )
    except (openai.BadRequestError, openai.AuthenticationError,
            openai.PermissionDeniedError, openai.NotFoundError) as e:
        raise ApplicationError(f"LLM request rejected: {e}", non_retryable=True) from e

    calls = [ToolCall(id=item.call_id, name=item.name,
                      args=json.loads(item.arguments))
             for item in resp.output if item.type == "function_call"]
    provider_items = [item.model_dump(mode="json", exclude_none=True)
                      for item in resp.output]
    return LLMResponse(message=ChatMessage(
        role="assistant",
        content=resp.output_text,
        tool_calls=calls,
        provider_items=provider_items,
    ))
