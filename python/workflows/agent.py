"""SupportAgentWorkflow — the durable agentic ReAct loop.

This file IS the demo. The numbered comments are slide 28's five primitives:
  01 Receive Input · 02 Plan · 03 Execute Tools · 04 Persist State · 05 Loop/Terminate

The agentic loop is just a `while` loop — Temporal makes it durable,
retryable, and pausable-for-humans.
"""

from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from activities.llm import call_llm
    from activities.tools import execute_tool
    from models.types import (
        ApprovalDecision,
        ChatMessage,
        LLMRequest,
        PendingPurchase,
        ToolRequest,
        TurnResult,
    )
    from prompts import system_prompt


@workflow.defn
class SupportAgentWorkflow:
    def __init__(self) -> None:
        self.messages: list[ChatMessage] = [] 
        self.pending_purchase: PendingPurchase | None = None
        self.approval: ApprovalDecision | None = None
        self.turn_in_progress: bool = False

    @workflow.run
    async def run(self, customer_email: str) -> None:
        self.messages.append(ChatMessage(role="system", content=system_prompt(customer_email)))
        workflow_id = workflow.info().workflow_id

        while True: 
            await workflow.wait_condition(lambda: self.turn_in_progress)

            while True:  # the ReAct loop for this turn
                plan_response = await workflow.execute_activity(
                    call_llm,
                    LLMRequest(messages=self.messages),
                    start_to_close_timeout=timedelta(seconds=60),
                )
                self.messages.append(plan_response.message)

                if not plan_response.message.tool_calls:
                    break

                for call in plan_response.message.tool_calls:
                    if call.name == "purchase_tracks":
                        self.pending_purchase = PendingPurchase(
                            approval_id=f"{call.id}:{len(self.messages)}",
                            track_ids=call.args.get("track_ids", []),
                            description=call.args.get("summary"),
                        )
                        await workflow.wait_condition(lambda: self.approval is not None)
                        decision, self.approval, self.pending_purchase = self.approval, None, None

                        if not decision.approved:
                            reason = f" Reason: {decision.reason}" if decision.reason else ""
                            result = f"The customer's approver DECLINED this purchase.{reason}"
                        else:
                            result = await workflow.execute_activity(
                                execute_tool,
                                ToolRequest(
                                    call=call,
                                    customer_email=customer_email,
                                    idempotency_key=f"{workflow_id}:{call.id}",
                                ),
                                start_to_close_timeout=timedelta(seconds=30),
                                summary=call.name,  # shows the tool name in the UI
                            )

                    else:
                        result = await workflow.execute_activity(
                            execute_tool,
                            ToolRequest(call=call, customer_email=customer_email),
                            start_to_close_timeout=timedelta(seconds=30),
                            summary=call.name,
                        )
                    self.messages.append(
                        ChatMessage(role="tool", content=result, tool_call_id=call.id)
                    )

            self.turn_in_progress = False
    

    @workflow.update
    async def send_message(self, text: str) -> TurnResult:
        """One chat turn: append the message, wake the loop, wait until the
        turn settles — a final reply OR parked on a purchase approval."""
        if self.turn_in_progress:
            await workflow.wait_condition(
                lambda: not self.turn_in_progress or self.pending_purchase is not None
            )
        if self.pending_purchase is not None:
            raise RuntimeError("purchase approval is still pending")
        turn_start = len(self.messages)
        self.messages.append(ChatMessage(role="user", content=text))
        self.turn_in_progress = True
        await workflow.wait_condition(
            lambda: not self.turn_in_progress or self.pending_purchase is not None
        )
        reply = self._last_assistant_text(since=turn_start)  # only THIS turn's text
        if self.pending_purchase is not None:
            return TurnResult(status="awaiting_approval", reply=reply)
        return TurnResult(status="reply", reply=reply)

    @workflow.update
    def approve_purchase(
        self, approval_id: str, decision: ApprovalDecision
    ) -> None:
        if self.pending_purchase is None:
            raise RuntimeError("nothing pending")
        if self.pending_purchase.approval_id != approval_id:
            raise RuntimeError("approval request is stale")
        self.approval = decision

    @workflow.query
    def transcript(self) -> list[ChatMessage]:
        """Display view: only user/assistant messages with text."""
        return [m.model_copy(update={"provider_items": []}) for m in self.messages
                if m.role in ("user", "assistant") and m.content]

    @workflow.query
    def pending_approval(self) -> PendingPurchase | None:
        return self.pending_purchase

    def _last_assistant_text(self, since: int = 0) -> str:
        for m in reversed(self.messages[since:]):
            if m.role == "assistant" and m.content:
                return m.content
        return ""
