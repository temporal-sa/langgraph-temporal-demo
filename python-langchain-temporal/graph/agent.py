"""LangGraph definition for the Temporal-backed support agent."""

from datetime import timedelta
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

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
    customer_email: str
    messages: list[ChatMessage]
    pending_purchase: PendingPurchase | None
    waiting_call: ToolCall | None
    remaining_calls: list[ToolCall]
    approval: ApprovalDecision | None


async def plan(state: AgentState) -> dict:
    messages = _messages(state["messages"])
    response = await call_llm(LLMRequest(messages=messages))
    return {"messages": [*messages, response.message]}


async def route_after_plan(state: AgentState) -> Literal["tools", "__end__"]:
    last_message = _message(state["messages"][-1])
    return "tools" if last_message.tool_calls else END


async def route_from_start(state: AgentState) -> Literal["plan", "tools"]:
    if state.get("waiting_call") is not None and state.get("approval") is not None:
        return "tools"
    return "plan"


async def route_after_tools(state: AgentState) -> Literal["plan", "__end__"]:
    return END if state.get("pending_purchase") is not None else "plan"


def execute_tools(state: AgentState) -> dict:
    messages = _messages(state["messages"])
    calls = _calls_to_process(state)
    update = {
        "messages": messages,
        "pending_purchase": None,
        "waiting_call": None,
        "remaining_calls": [],
        "approval": None,
    }

    while calls:
        call = calls.pop(0)

        if call.name == "purchase_tracks" and state.get("approval") is None:
            return {
                **update,
                "messages": messages,
                "pending_purchase": PendingPurchase(
                    track_ids=call.args.get("track_ids", []),
                    description=call.args.get("summary"),
                ),
                "waiting_call": call,
                "remaining_calls": calls,
            }

        if call.name == "purchase_tracks":
            decision = _approval(state["approval"])
            if decision is None:
                raise RuntimeError("purchase approval is required")
            if decision.approved:
                result = execute_tool(
                    ToolRequest(call=call, customer_email=state["customer_email"])
                )
            else:
                reason = f" Reason: {decision.reason}" if decision.reason else ""
                result = f"The customer's approver DECLINED this purchase.{reason}"
        else:
            result = execute_tool(
                ToolRequest(call=call, customer_email=state["customer_email"])
            )

        messages.append(ChatMessage(role="tool", content=result, tool_call_id=call.id))
        state = {**state, "approval": None}

    return update


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
    builder.add_conditional_edges(
        START, route_from_start, {"plan": "plan", "tools": "tools"}
    )
    builder.add_conditional_edges(
        "plan", route_after_plan, {"tools": "tools", END: END}
    )
    builder.add_conditional_edges(
        "tools", route_after_tools, {"plan": "plan", END: END}
    )
    return builder


def _calls_to_process(state: AgentState) -> list[ToolCall]:
    waiting_call = state.get("waiting_call")
    if waiting_call is not None:
        return [
            _tool_call(waiting_call),
            *[_tool_call(call) for call in state.get("remaining_calls", [])],
        ]
    return list(_message(state["messages"][-1]).tool_calls)


def _messages(values: list[ChatMessage | dict[str, Any]]) -> list[ChatMessage]:
    return [_message(value) for value in values]


def _message(value: ChatMessage | dict[str, Any]) -> ChatMessage:
    if isinstance(value, ChatMessage):
        return value
    return ChatMessage.model_validate(value)


def _tool_call(value: ToolCall | dict[str, Any]) -> ToolCall:
    if isinstance(value, ToolCall):
        return value
    return ToolCall.model_validate(value)


def _approval(value: ApprovalDecision | dict[str, Any] | None) -> ApprovalDecision | None:
    if value is None or isinstance(value, ApprovalDecision):
        return value
    return ApprovalDecision.model_validate(value)
