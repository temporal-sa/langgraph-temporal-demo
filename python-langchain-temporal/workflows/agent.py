"""Temporal workflow that runs the support-agent LangGraph graph.

The LangGraph nodes run through temporalio.contrib.langgraph. The Workflow keeps
conversation state and human approval state; the plugin turns the graph's LLM
and tool nodes into Temporal Activities.
"""

from typing import Any

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from graph.agent import GRAPH_NAME, AgentState
    from models.types import ApprovalDecision, ChatMessage, PendingPurchase, TurnResult
    from prompts import system_prompt
    from temporalio.contrib.langgraph import graph


@workflow.defn
class SupportAgentWorkflow:
    def __init__(self) -> None:
        self.state: AgentState | None = None
        self.turn_in_progress = False

    @workflow.run
    async def run(self, customer_email: str) -> None:
        self.state = {
            "customer_email": customer_email,
            "messages": [
                ChatMessage(role="system", content=system_prompt(customer_email))
            ],
            "pending_purchase": None,
            "waiting_call": None,
            "remaining_calls": [],
            "approval": None,
        }

        app = graph(GRAPH_NAME).compile()
        while True:
            await workflow.wait_condition(lambda: self.turn_in_progress)
            self.state = await app.ainvoke(self.state)
            self.turn_in_progress = False

    @workflow.update
    async def send_message(self, text: str) -> TurnResult:
        await workflow.wait_condition(lambda: self.state is not None)
        state = self._state()
        if self.turn_in_progress:
            raise RuntimeError("a turn is already in progress")
        if state["pending_purchase"] is not None:
            raise RuntimeError("purchase approval is still pending")

        turn_start = len(state["messages"])
        self.state = {
            **state,
            "messages": [*state["messages"], ChatMessage(role="user", content=text)],
            "approval": None,
        }
        self.turn_in_progress = True
        await workflow.wait_condition(
            lambda: not self.turn_in_progress
            or self._state()["pending_purchase"] is not None
        )

        state = self._state()
        reply = self._last_assistant_text(since=turn_start)
        if state["pending_purchase"] is not None:
            return TurnResult(status="awaiting_approval", reply=reply)
        return TurnResult(status="reply", reply=reply)

    @workflow.signal
    def approve_purchase(self, decision: ApprovalDecision) -> None:
        if self.state is None:
            return
        if self.state["pending_purchase"] is None:
            return
        self.state = {
            **self.state,
            "approval": decision,
            "pending_purchase": None,
        }
        self.turn_in_progress = True

    @workflow.query
    def transcript(self) -> list[ChatMessage]:
        if self.state is None:
            return []
        return [
            message
            for message in _messages(self.state["messages"])
            if message.role in ("user", "assistant") and message.content
        ]

    @workflow.query
    def pending_approval(self) -> PendingPurchase | None:
        if self.state is None:
            return None
        return _pending_purchase(self.state["pending_purchase"])

    def _state(self) -> AgentState:
        if self.state is None:
            raise RuntimeError("workflow state is not initialized")
        return self.state

    def _last_assistant_text(self, since: int = 0) -> str:
        for message in reversed(_messages(self._state()["messages"][since:])):
            if message.role == "assistant" and message.content:
                return message.content
        return ""


def _messages(values: list[ChatMessage | dict[str, Any]]) -> list[ChatMessage]:
    return [_message(value) for value in values]


def _message(value: ChatMessage | dict[str, Any]) -> ChatMessage:
    if isinstance(value, ChatMessage):
        return value
    return ChatMessage.model_validate(value)


def _pending_purchase(
    value: PendingPurchase | dict[str, Any] | None,
) -> PendingPurchase | None:
    if value is None or isinstance(value, PendingPurchase):
        return value
    return PendingPurchase.model_validate(value)
