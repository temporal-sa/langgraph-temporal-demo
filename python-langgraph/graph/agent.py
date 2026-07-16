"""Standalone LangGraph agent with checkpoint-backed conversation state.

LangGraph owns the ReAct loop, native interrupts, node retry policies, and
checkpoint persistence. The hosting process still owns *running* a graph
invocation: after process loss a durable checkpoint can be resumed, but nothing
automatically starts that work again.
"""

import asyncio
from datetime import timedelta
from typing import Any, Literal, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, GraphOutput, RetryPolicy, interrupt

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


class UnknownConversationError(KeyError):
    pass


class PendingApprovalError(RuntimeError):
    pass


class NoPendingApprovalError(RuntimeError):
    pass


class StaleApprovalError(RuntimeError):
    pass


class TurnInProgressError(RuntimeError):
    pass


class TurnNotResumableError(RuntimeError):
    pass


class AgentRunError(RuntimeError):
    pass


class AgentState(TypedDict):
    conversation_id: str
    customer_email: str
    messages: list[dict[str, Any]]
    turn_phase: Literal["idle", "running"]


class ConversationStatus(TypedDict):
    status: Literal["idle", "running", "awaiting_approval", "interrupted"]
    resumable: bool


def _retryable(error: Exception) -> bool:
    """Retry transient runtime failures, not malformed or rejected inputs."""

    return not isinstance(error, (ValueError, TypeError, KeyError))


NODE_RETRY_POLICY = RetryPolicy(
    initial_interval=1,
    backoff_factor=2,
    max_interval=8,
    max_attempts=3,
    jitter=True,
    retry_on=_retryable,
)


async def _plan(state: AgentState) -> dict:
    messages = _messages(state["messages"])
    response = await call_llm(LLMRequest(messages=messages))
    return {
        "messages": _message_dicts([*messages, response.message]),
        "turn_phase": "running" if response.message.tool_calls else "idle",
    }


def _route_after_plan(state: AgentState) -> Literal["tools", "__end__"]:
    last_message = _message(state["messages"][-1])
    return "tools" if last_message.tool_calls else END


async def _execute_tools(state: AgentState) -> dict:
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
            result = await asyncio.to_thread(
                execute_tool,
                ToolRequest(
                    call=call,
                    customer_email=state["customer_email"],
                    idempotency_key=f"{state['conversation_id']}:{call.id}",
                ),
            )
        else:
            reason = f" Reason: {decision.reason}" if decision.reason else ""
            result = f"The customer's approver DECLINED this purchase.{reason}"
    else:
        result = await asyncio.to_thread(
            execute_tool,
            ToolRequest(call=call, customer_email=state["customer_email"]),
        )

    messages.append(ChatMessage(role="tool", content=result, tool_call_id=call.id))
    return {"messages": _message_dicts(messages), "turn_phase": "running"}


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


def build_graph(
    checkpointer,
    *,
    plan_timeout: timedelta = timedelta(seconds=60),
    tool_timeout: timedelta = timedelta(seconds=30),
):
    """Compile one reusable graph against the caller-owned checkpointer."""

    builder = StateGraph(AgentState)
    builder.add_node(
        "plan",
        _plan,
        retry_policy=NODE_RETRY_POLICY,
        timeout=plan_timeout,
    )
    builder.add_node(
        "tools",
        _execute_tools,
        retry_policy=NODE_RETRY_POLICY,
        timeout=tool_timeout,
    )
    builder.add_edge(START, "plan")
    builder.add_conditional_edges(
        "plan", _route_after_plan, {"tools": "tools", END: END}
    )
    builder.add_conditional_edges(
        "tools", _route_after_tools, {"tools": "tools", "plan": "plan"}
    )
    return builder.compile(checkpointer=checkpointer)


class SupportAgentService:
    """API-facing execution facade; durable state remains in the checkpointer."""

    def __init__(self, graph) -> None:
        self._graph = graph
        self._locks: dict[str, asyncio.Lock] = {}
        self._active_runs: dict[str, asyncio.Task[GraphOutput]] = {}

    async def create(self, conversation_id: str, customer_email: str) -> None:
        config = _config(conversation_id)
        current = await self._graph.aget_state(config)
        if current.values:
            raise ValueError("conversation already exists")
        await self._graph.aupdate_state(
            config,
            {
                "conversation_id": conversation_id,
                "customer_email": customer_email,
                "messages": [
                    ChatMessage(
                        role="system", content=system_prompt(customer_email)
                    ).model_dump(mode="json")
                ],
                "turn_phase": "idle",
            },
        )

    async def send_message(self, conversation_id: str, text: str) -> TurnResult:
        if conversation_id in self._active_runs:
            raise TurnInProgressError("a turn is already running")
        async with self._lock(conversation_id):
            snapshot = await self._snapshot(conversation_id)
            status = self._status(conversation_id, snapshot)
            if status["status"] == "awaiting_approval":
                raise PendingApprovalError("purchase approval is still pending")
            if status["status"] != "idle":
                raise TurnInProgressError(
                    "the previous turn is interrupted; "
                    "resume it before sending a message"
                )

            state = _agent_state(snapshot.values)
            turn_start = len(state["messages"])
            result = await self._invoke(
                conversation_id,
                {
                    **state,
                    "messages": [
                        *state["messages"],
                        ChatMessage(role="user", content=text).model_dump(mode="json"),
                    ],
                    "turn_phase": "running",
                },
            )
            return _turn_result(result, since=turn_start)

    async def approve_purchase(
        self,
        conversation_id: str,
        approval_id: str,
        decision: ApprovalDecision,
    ) -> TurnResult:
        if conversation_id in self._active_runs:
            raise TurnInProgressError("a turn is already running")
        async with self._lock(conversation_id):
            snapshot = await self._snapshot(conversation_id)
            pending = _pending_from_snapshot(snapshot)
            if pending is None:
                raise NoPendingApprovalError("nothing pending")
            if pending.approval_id != approval_id:
                raise StaleApprovalError("approval request is stale")

            turn_start = len(_agent_state(snapshot.values)["messages"])
            result = await self._invoke(
                conversation_id,
                Command(resume=decision.model_dump(mode="json")),
            )
            return _turn_result(result, since=turn_start)

    async def resume(self, conversation_id: str) -> TurnResult:
        if conversation_id in self._active_runs:
            raise TurnInProgressError("a turn is already running")
        async with self._lock(conversation_id):
            snapshot = await self._snapshot(conversation_id)
            status = self._status(conversation_id, snapshot)
            if status["status"] != "interrupted":
                raise TurnNotResumableError("the conversation has no interrupted turn")

            state = _agent_state(snapshot.values)
            turn_start = _last_user_index(state["messages"])
            result = await self._invoke(conversation_id, None)
            return _turn_result(result, since=turn_start)

    async def transcript(self, conversation_id: str) -> list[ChatMessage]:
        state = _agent_state((await self._snapshot(conversation_id)).values)
        return [
            message
            for message in _messages(state["messages"])
            if message.role in ("user", "assistant") and message.content
        ]

    async def pending_approval(
        self, conversation_id: str
    ) -> PendingPurchase | None:
        return _pending_from_snapshot(await self._snapshot(conversation_id))

    async def status(self, conversation_id: str) -> ConversationStatus:
        return self._status(conversation_id, await self._snapshot(conversation_id))

    async def simulate_crash(self) -> None:
        """Drop all process-owned execution while preserving checkpoints."""

        tasks = list(self._active_runs.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._active_runs.clear()
        self._locks.clear()

    async def _snapshot(self, conversation_id: str):
        snapshot = await self._graph.aget_state(_config(conversation_id))
        if (
            not snapshot.values
            or snapshot.values.get("conversation_id") != conversation_id
        ):
            raise UnknownConversationError("unknown conversation")
        return snapshot

    def _status(self, conversation_id: str, snapshot) -> ConversationStatus:
        if _pending_from_snapshot(snapshot) is not None:
            return {"status": "awaiting_approval", "resumable": False}
        if conversation_id in self._active_runs:
            return {"status": "running", "resumable": False}
        state = _agent_state(snapshot.values)
        if state["turn_phase"] == "running":
            return {"status": "interrupted", "resumable": True}
        return {"status": "idle", "resumable": False}

    async def _invoke(
        self, conversation_id: str, graph_input: AgentState | Command | None
    ) -> GraphOutput:
        task = asyncio.create_task(
            self._graph.ainvoke(
                graph_input,
                _config(conversation_id),
                version="v2",
            )
        )
        self._active_runs[conversation_id] = task
        try:
            return await task
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise AgentRunError(str(error)) from error
        finally:
            if self._active_runs.get(conversation_id) is task:
                self._active_runs.pop(conversation_id, None)

    def _lock(self, conversation_id: str) -> asyncio.Lock:
        return self._locks.setdefault(conversation_id, asyncio.Lock())


def _config(conversation_id: str) -> RunnableConfig:
    return RunnableConfig({"configurable": {"thread_id": conversation_id}})


def _turn_result(result: GraphOutput, *, since: int) -> TurnResult:
    state = _agent_state(result.value)
    reply = _last_assistant_text(state["messages"], since=since)
    if _pending_from_interrupts(result.interrupts) is not None:
        return TurnResult(status="awaiting_approval", reply=reply)
    return TurnResult(status="reply", reply=reply)


def _pending_from_snapshot(snapshot) -> PendingPurchase | None:
    interrupts = tuple(
        value
        for task in snapshot.tasks
        for value in getattr(task, "interrupts", ())
    )
    return _pending_from_interrupts(interrupts)


def _pending_from_interrupts(interrupts: tuple) -> PendingPurchase | None:
    if not interrupts:
        return None
    return PendingPurchase.model_validate(interrupts[0].value)


def _last_user_index(messages: list[dict[str, Any]]) -> int:
    for index in range(len(messages) - 1, -1, -1):
        if _message(messages[index]).role == "user":
            return index
    return 0


def _last_assistant_text(
    messages: list[dict[str, Any]], since: int = 0
) -> str:
    for message in reversed(_messages(messages[since:])):
        if message.role == "assistant" and message.content:
            return message.content
    return ""


def _agent_state(value: dict[str, Any]) -> AgentState:
    return {
        "conversation_id": str(value["conversation_id"]),
        "customer_email": str(value["customer_email"]),
        "messages": _message_dicts(_messages(value["messages"])),
        "turn_phase": value.get("turn_phase", "idle"),
    }


def _messages(values: list[ChatMessage | dict[str, Any]]) -> list[ChatMessage]:
    return [_message(value) for value in values]


def _message(value: ChatMessage | dict[str, Any]) -> ChatMessage:
    if isinstance(value, ChatMessage):
        return value
    return ChatMessage.model_validate(value)


def _message_dicts(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    return [message.model_dump(mode="json") for message in messages]
