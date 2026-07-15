"""LangGraph support agent.

This is the standalone agent runtime. LangGraph owns the ReAct loop and native
human-in-the-loop interrupts; FastAPI or the CLI owns conversation storage and
user interaction.
"""

import asyncio
from typing import Any, Literal, TypedDict
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, GraphOutput, interrupt

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


class StaleApprovalError(RuntimeError):
    pass


class AgentState(TypedDict):
    conversation_id: str
    customer_email: str
    messages: list[dict[str, Any]]


async def _plan(state: AgentState) -> dict:
    messages = _messages(state["messages"])
    response = await call_llm(LLMRequest(messages=messages))
    return {"messages": _message_dicts([*messages, response.message])}


def _route_after_plan(state: AgentState) -> Literal["tools", "__end__"]:
    last_message = _message(state["messages"][-1])
    return "tools" if last_message.tool_calls else END


def _execute_tools(state: AgentState) -> dict:
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


def _route_after_tools(state: AgentState) -> Literal["tools", "plan"]:
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


def build_graph():
    builder = StateGraph(AgentState)
    builder.add_node("plan", _plan)
    builder.add_node("tools", _execute_tools)
    builder.add_edge(START, "plan")
    builder.add_conditional_edges("plan", _route_after_plan, {"tools": "tools", END: END})
    builder.add_conditional_edges(
        "tools", _route_after_tools, {"tools": "tools", "plan": "plan"}
    )
    return builder.compile(checkpointer=InMemorySaver())


class SupportAgentSession:
    def __init__(
        self, customer_email: str, conversation_id: str | None = None
    ) -> None:
        conversation_id = conversation_id or f"standalone-{uuid4()}"
        self._graph = build_graph()
        self._config = RunnableConfig(
            {"configurable": {"thread_id": conversation_id}}
        )
        self._lock = asyncio.Lock()
        self._state: AgentState = {
            "conversation_id": conversation_id,
            "customer_email": customer_email,
            "messages": [
                ChatMessage(
                    role="system", content=system_prompt(customer_email)
                ).model_dump(mode="json")
            ],
        }
        self._pending_purchase: PendingPurchase | None = None

    async def send_message(self, text: str) -> TurnResult:
        async with self._lock:
            if self._pending_purchase is not None:
                raise PendingApprovalError("purchase approval is still pending")

            turn_start = len(self._state["messages"])
            await self._invoke(
                {
                    **self._state,
                    "messages": [
                        *self._state["messages"],
                        ChatMessage(role="user", content=text).model_dump(mode="json"),
                    ],
                }
            )
            return self._turn_result(turn_start)

    async def approve_purchase(
        self, approval_id: str, decision: ApprovalDecision
    ) -> TurnResult:
        async with self._lock:
            pending = self._pending_purchase
            if pending is None:
                raise NoPendingApprovalError("nothing pending")
            if pending.approval_id != approval_id:
                raise StaleApprovalError("approval request is stale")

            turn_start = len(self._state["messages"])
            await self._invoke(Command(resume=decision.model_dump(mode="json")))
            return self._turn_result(turn_start)

    def transcript(self) -> list[ChatMessage]:
        return [
            message
            for message in _messages(self._state["messages"])
            if message.role in ("user", "assistant") and message.content
        ]

    def pending_approval(self) -> PendingPurchase | None:
        return self._pending_purchase

    async def _invoke(self, graph_input: AgentState | Command) -> None:
        result: GraphOutput = await self._graph.ainvoke(
            graph_input,
            self._config,
            version="v2",
        )
        self._state = result.value
        self._pending_purchase = _pending_from_interrupts(result.interrupts)

    def _turn_result(self, since: int) -> TurnResult:
        reply = _last_assistant_text(self._state["messages"], since=since)
        if self._pending_purchase is not None:
            return TurnResult(status="awaiting_approval", reply=reply)
        return TurnResult(status="reply", reply=reply)


class ConversationStore:
    def __init__(self) -> None:
        self._sessions: dict[str, SupportAgentSession] = {}

    def create(self, conversation_id: str, customer_email: str) -> None:
        self._sessions[conversation_id] = SupportAgentSession(
            customer_email,
            conversation_id,
        )

    def get(self, conversation_id: str) -> SupportAgentSession:
        try:
            return self._sessions[conversation_id]
        except KeyError as e:
            raise KeyError("unknown conversation") from e


def _last_assistant_text(
    messages: list[dict[str, Any]], since: int = 0
) -> str:
    for message in reversed(_messages(messages[since:])):
        if message.role == "assistant" and message.content:
            return message.content
    return ""


def _pending_from_interrupts(interrupts: tuple) -> PendingPurchase | None:
    if not interrupts:
        return None
    return PendingPurchase.model_validate(interrupts[0].value)


def _messages(values: list[ChatMessage | dict[str, Any]]) -> list[ChatMessage]:
    return [_message(value) for value in values]


def _message(value: ChatMessage | dict[str, Any]) -> ChatMessage:
    if isinstance(value, ChatMessage):
        return value
    return ChatMessage.model_validate(value)


def _message_dicts(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    return [message.model_dump(mode="json") for message in messages]
