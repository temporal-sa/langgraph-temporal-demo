"""LangGraph definition for the Temporal-backed support agent."""

from datetime import timedelta
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from activities.llm import call_llm
from activities.tools import execute_tool
from models.types import (
    ApprovalDecision,
    ChatMessage,
    LLMRequest,
    PendingPurchase,
    ToolCall,
    ToolRequest,
)

GRAPH_NAME = "support-agent-temporal-langgraph"


class AgentState(TypedDict):
    conversation_id: str
    customer_email: str
    messages: list[dict[str, Any]]


async def plan(state: AgentState) -> dict:
    messages = _messages(state["messages"])
    response = await call_llm(LLMRequest(messages=messages))
    return {"messages": _message_dicts([*messages, response.message])}


async def route_after_plan(state: AgentState) -> Literal["tools", "__end__"]:
    last_message = _message(state["messages"][-1])
    return "tools" if last_message.tool_calls else END


def execute_tools(state: AgentState) -> dict:
    messages = _messages(state["messages"])
    call = _next_tool_call(messages)
    if call is None:
        raise RuntimeError("tools node has no unprocessed tool call")

    if call.name == "purchase_tracks":
        pending = PendingPurchase(
            approval_id=f"{call.id}:{len(messages)}",
            track_ids=call.args.get("track_ids", []),
            description=call.args.get("summary"),
        )
        resume_value = interrupt(pending.model_dump(mode="json"))
        decision = ApprovalDecision.model_validate(resume_value)
        if decision.approved:
            result = execute_tool(
                ToolRequest(
                    call=call,
                    customer_email=state["customer_email"],
                    idempotency_key=f"{state['conversation_id']}:{call.id}",
                )
            )
        else:
            reason = f" Reason: {decision.reason}" if decision.reason else ""
            result = f"The customer's approver DECLINED this purchase.{reason}"
    else:
        result = execute_tool(
            ToolRequest(call=call, customer_email=state["customer_email"])
        )

    messages.append(ChatMessage(role="tool", content=result, tool_call_id=call.id))

    return {"messages": _message_dicts(messages)}


async def route_after_tools(state: AgentState) -> Literal["tools", "plan"]:
    return "tools" if _next_tool_call(_messages(state["messages"])) else "plan"


def _next_tool_call(messages: list[ChatMessage]) -> ToolCall | None:
    """Return the first call from the latest plan without a tool response."""
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.role != "assistant" or not message.tool_calls:
            continue
        completed = {
            item.tool_call_id
            for item in messages[index + 1 :]
            if item.role == "tool" and item.tool_call_id
        }
        return next(
            (call for call in message.tool_calls if call.id not in completed),
            None,
        )
    return None


def build_graph() -> StateGraph:
    builder = StateGraph(AgentState)
    builder.add_node(
        "plan",
        plan,
        metadata={
            "execute_in": "activity",
            "start_to_close_timeout": timedelta(seconds=60),
        },
    )
    builder.add_node(
        "tools",
        execute_tools,
        metadata={
            "execute_in": "activity",
            "start_to_close_timeout": timedelta(seconds=30),
        },
    )
    builder.add_edge(START, "plan")
    builder.add_conditional_edges(
        "plan", route_after_plan, {"tools": "tools", END: END}
    )
    builder.add_conditional_edges(
        "tools", route_after_tools, {"tools": "tools", "plan": "plan"}
    )
    return builder


def _messages(values: list[ChatMessage | dict[str, Any]]) -> list[ChatMessage]:
    return [_message(value) for value in values]


def _message(value: ChatMessage | dict[str, Any]) -> ChatMessage:
    if isinstance(value, ChatMessage):
        return value
    return ChatMessage.model_validate(value)


def _message_dicts(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    return [message.model_dump(mode="json") for message in messages]
