"""LangGraph support agent.

This is the standalone agent runtime. LangGraph owns the ReAct loop; FastAPI or
the CLI owns conversation storage and user interaction.
"""

import asyncio
from typing import Literal, TypedDict

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
    TurnResult,
)
from prompts import system_prompt


class PendingApprovalError(RuntimeError):
    pass


class NoPendingApprovalError(RuntimeError):
    pass


class AgentState(TypedDict):
    customer_email: str
    messages: list[ChatMessage]
    pending_purchase: PendingPurchase | None
    waiting_call: ToolCall | None
    remaining_calls: list[ToolCall]
    approval: ApprovalDecision | None


async def _plan(state: AgentState) -> dict:
    response = await call_llm(LLMRequest(messages=state["messages"]))
    return {"messages": [*state["messages"], response.message]}


def _route_after_plan(state: AgentState) -> Literal["tools", "__end__"]:
    last_message = state["messages"][-1]
    return "tools" if last_message.tool_calls else END


def _route_from_start(state: AgentState) -> Literal["plan", "tools"]:
    if state.get("waiting_call") is not None and state.get("approval") is not None:
        return "tools"
    return "plan"


def _route_after_tools(state: AgentState) -> Literal["plan", "__end__"]:
    return END if state.get("pending_purchase") is not None else "plan"


def _execute_tools(state: AgentState) -> dict:
    messages = list(state["messages"])
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
            decision = state["approval"]
            if decision is None:
                raise PendingApprovalError("purchase approval is required")
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


def _calls_to_process(state: AgentState) -> list[ToolCall]:
    waiting_call = state.get("waiting_call")
    if waiting_call is not None:
        return [waiting_call, *state.get("remaining_calls", [])]
    return list(state["messages"][-1].tool_calls)


def build_graph():
    builder = StateGraph(AgentState)
    builder.add_node("plan", _plan)
    builder.add_node("tools", _execute_tools)
    builder.add_conditional_edges(START, _route_from_start, {"plan": "plan", "tools": "tools"})
    builder.add_conditional_edges("plan", _route_after_plan, {"tools": "tools", END: END})
    builder.add_conditional_edges("tools", _route_after_tools, {"plan": "plan", END: END})
    return builder.compile()


class SupportAgentSession:
    def __init__(self, customer_email: str) -> None:
        self._graph = build_graph()
        self._lock = asyncio.Lock()
        self._state: AgentState = {
            "customer_email": customer_email,
            "messages": [ChatMessage(role="system", content=system_prompt(customer_email))],
            "pending_purchase": None,
            "waiting_call": None,
            "remaining_calls": [],
            "approval": None,
        }

    async def send_message(self, text: str) -> TurnResult:
        async with self._lock:
            if self._state["pending_purchase"] is not None:
                raise PendingApprovalError("purchase approval is still pending")

            turn_start = len(self._state["messages"])
            self._state = await self._graph.ainvoke(
                {
                    **self._state,
                    "messages": [
                        *self._state["messages"],
                        ChatMessage(role="user", content=text),
                    ],
                    "approval": None,
                }
            )
            return self._turn_result(turn_start)

    async def approve_purchase(self, decision: ApprovalDecision) -> TurnResult:
        async with self._lock:
            if self._state["pending_purchase"] is None:
                raise NoPendingApprovalError("nothing pending")

            turn_start = len(self._state["messages"])
            self._state = await self._graph.ainvoke(
                {
                    **self._state,
                    "approval": decision,
                    "pending_purchase": None,
                }
            )
            return self._turn_result(turn_start)

    def transcript(self) -> list[ChatMessage]:
        return [
            message
            for message in self._state["messages"]
            if message.role in ("user", "assistant") and message.content
        ]

    def pending_approval(self) -> PendingPurchase | None:
        return self._state["pending_purchase"]

    def _turn_result(self, since: int) -> TurnResult:
        reply = _last_assistant_text(self._state["messages"], since=since)
        if self._state["pending_purchase"] is not None:
            return TurnResult(status="awaiting_approval", reply=reply)
        return TurnResult(status="reply", reply=reply)


class ConversationStore:
    def __init__(self) -> None:
        self._sessions: dict[str, SupportAgentSession] = {}

    def create(self, conversation_id: str, customer_email: str) -> None:
        self._sessions[conversation_id] = SupportAgentSession(customer_email)

    def get(self, conversation_id: str) -> SupportAgentSession:
        try:
            return self._sessions[conversation_id]
        except KeyError as e:
            raise KeyError("unknown conversation") from e


def _last_assistant_text(messages: list[ChatMessage], since: int = 0) -> str:
    for message in reversed(messages[since:]):
        if message.role == "assistant" and message.content:
            return message.content
    return ""
