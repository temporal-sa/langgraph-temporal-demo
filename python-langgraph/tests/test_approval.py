import unittest
from unittest.mock import AsyncMock, patch

from graph.agent import StaleApprovalError, SupportAgentSession
from models.types import (
    ApprovalDecision,
    ChatMessage,
    LLMResponse,
    PendingPurchase,
    ToolCall,
)


class ApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_approval_is_rejected_without_mutating_state(self) -> None:
        session = SupportAgentSession("sa@temporal.io")
        pending = PendingPurchase(
            approval_id="approval-current", track_ids=[1], description="One track"
        )
        session._pending_purchase = pending

        with self.assertRaisesRegex(StaleApprovalError, "stale"):
            await session.approve_purchase(
                "approval-old", ApprovalDecision(approved=True)
            )

        self.assertEqual(session.pending_approval(), pending)

    async def test_purchase_uses_interrupt_and_command_resume(self) -> None:
        session = SupportAgentSession("sa@temporal.io")
        purchase = ToolCall(
            id="purchase-1",
            name="purchase_tracks",
            args={"track_ids": [3], "summary": "One track"},
        )
        responses = [
            LLMResponse(
                message=ChatMessage(role="assistant", tool_calls=[purchase])
            ),
            LLMResponse(
                message=ChatMessage(role="assistant", content="Purchase complete")
            ),
        ]

        with (
            patch("graph.agent.call_llm", new=AsyncMock(side_effect=responses)),
            patch("graph.agent.execute_tool", return_value='{"ok": true}') as tool,
        ):
            paused = await session.send_message("Buy it")
            pending = session.pending_approval()

            self.assertEqual(paused.status, "awaiting_approval")
            self.assertIsNotNone(pending)
            assert pending is not None
            self.assertEqual(pending.track_ids, [3])
            self.assertEqual(
                set(session._state),
                {"conversation_id", "customer_email", "messages"},
            )
            tool.assert_not_called()

            resumed = await session.approve_purchase(
                pending.approval_id,
                ApprovalDecision(approved=True),
            )

        self.assertEqual(resumed.status, "reply")
        self.assertEqual(resumed.reply, "Purchase complete")
        self.assertIsNone(session.pending_approval())
        tool.assert_called_once()
        self.assertEqual(
            tool.call_args.args[0].idempotency_key,
            f"{session._state['conversation_id']}:purchase-1",
        )


if __name__ == "__main__":
    unittest.main()
