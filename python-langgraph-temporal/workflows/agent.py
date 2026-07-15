"""Temporal workflow that runs the support-agent LangGraph graph.

The LangGraph nodes run through temporalio.contrib.langgraph. LangGraph's
native interrupt/Command API owns the human approval pause and resume, while
the plugin turns the graph's LLM and tool nodes into Temporal Activities.
"""

from typing import Any

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from langchain_core.runnables import RunnableConfig
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command, GraphOutput

    from graph.agent import GRAPH_NAME, AgentState
    from models.types import ApprovalDecision, ChatMessage, PendingPurchase, TurnResult
    from prompts import system_prompt
    from temporalio.contrib.langgraph import graph


@workflow.defn
class SupportAgentWorkflow:
    def __init__(self) -> None:
        self.state: AgentState | None = None
        self.pending_purchase: PendingPurchase | None = None
        self.graph_input: AgentState | Command | None = None
        self.turn_in_progress = False

    @workflow.run
    async def run(self, customer_email: str) -> None:
        self.state = {
            "conversation_id": workflow.info().workflow_id,
            "customer_email": customer_email,
            "messages": [
                ChatMessage(
                    role="system", content=system_prompt(customer_email)
                ).model_dump(mode="json")
            ],
        }

        app = graph(GRAPH_NAME).compile(checkpointer=InMemorySaver())
        config = RunnableConfig(
            {"configurable": {"thread_id": workflow.info().workflow_id}}
        )
        while True:
            await workflow.wait_condition(lambda: self.turn_in_progress)
            graph_input = self.graph_input
            if graph_input is None:
                raise RuntimeError("graph input is not initialized")

            result: GraphOutput = await app.ainvoke(
                graph_input,
                config,
                version="v2",
            )
            self.state = _agent_state(result.value)
            self.pending_purchase = _pending_from_interrupts(result.interrupts)
            self.graph_input = None
            self.turn_in_progress = False

    @workflow.update
    async def send_message(self, text: str) -> TurnResult:
        await workflow.wait_condition(lambda: self.state is not None)
        state = self._state()
        if self.turn_in_progress:
            await workflow.wait_condition(lambda: not self.turn_in_progress)
            state = self._state()
        if self.pending_purchase is not None:
            raise RuntimeError("purchase approval is still pending")

        turn_start = len(state["messages"])
        self.graph_input = {
            **state,
            "messages": [
                *state["messages"],
                ChatMessage(role="user", content=text).model_dump(mode="json"),
            ],
        }
        self.turn_in_progress = True
        await workflow.wait_condition(lambda: not self.turn_in_progress)

        reply = self._last_assistant_text(since=turn_start)
        if self.pending_purchase is not None:
            return TurnResult(status="awaiting_approval", reply=reply)
        return TurnResult(status="reply", reply=reply)

    @workflow.update
    def approve_purchase(
        self, approval_id: str, decision: ApprovalDecision
    ) -> None:
        if self.state is None:
            raise RuntimeError("workflow state is not initialized")
        pending = self.pending_purchase
        if pending is None:
            raise RuntimeError("nothing pending")
        if pending.approval_id != approval_id:
            raise RuntimeError("approval request is stale")

        self.graph_input = Command(resume=decision.model_dump(mode="json"))
        self.pending_purchase = None
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
        return self.pending_purchase

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


def _agent_state(value: dict[str, Any]) -> AgentState:
    return {
        "conversation_id": str(value["conversation_id"]),
        "customer_email": str(value["customer_email"]),
        "messages": [
            message.model_dump(mode="json") for message in _messages(value["messages"])
        ],
    }


def _pending_from_interrupts(interrupts: tuple) -> PendingPurchase | None:
    if not interrupts:
        return None
    return _pending_purchase(interrupts[0].value)
