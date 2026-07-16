import asyncio
from datetime import timedelta
import unittest
from unittest.mock import AsyncMock, patch

from langgraph.checkpoint.memory import InMemorySaver

from graph.agent import (
    AgentRunError,
    NODE_RETRY_POLICY,
    StaleApprovalError,
    SupportAgentService,
    TurnNotResumableError,
    _execute_tools,
    _retryable,
    build_graph,
)
from models.types import ApprovalDecision, ChatMessage, LLMResponse, ToolCall


class ApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.graph = build_graph(InMemorySaver())
        self.service = SupportAgentService(self.graph)
        await self.service.create("conversation-1", "sa@temporal.io")

    async def test_stale_approval_is_rejected_without_mutating_checkpoint(self) -> None:
        purchase = ToolCall(
            id="purchase-1",
            name="purchase_tracks",
            args={"track_ids": [3], "summary": "One track"},
        )
        with patch(
            "graph.agent.call_llm",
            new=AsyncMock(
                return_value=LLMResponse(
                    message=ChatMessage(role="assistant", tool_calls=[purchase])
                )
            ),
        ):
            await self.service.send_message("conversation-1", "Buy it")

        pending = await self.service.pending_approval("conversation-1")
        self.assertIsNotNone(pending)
        with self.assertRaisesRegex(StaleApprovalError, "stale"):
            await self.service.approve_purchase(
                "conversation-1",
                "approval-old",
                ApprovalDecision(approved=True),
            )
        self.assertEqual(
            await self.service.pending_approval("conversation-1"), pending
        )

    async def test_purchase_uses_interrupt_command_and_idempotency_key(self) -> None:
        purchase = ToolCall(
            id="purchase-1",
            name="purchase_tracks",
            args={"track_ids": [3], "summary": "One track"},
        )
        responses = [
            LLMResponse(message=ChatMessage(role="assistant", tool_calls=[purchase])),
            LLMResponse(
                message=ChatMessage(role="assistant", content="Purchase complete")
            ),
        ]

        with (
            patch("graph.agent.call_llm", new=AsyncMock(side_effect=responses)),
            patch("graph.agent.execute_tool", return_value='{"ok": true}') as tool,
        ):
            paused = await self.service.send_message("conversation-1", "Buy it")
            pending = await self.service.pending_approval("conversation-1")
            self.assertEqual(paused.status, "awaiting_approval")
            self.assertIsNotNone(pending)
            assert pending is not None
            self.assertEqual(
                await self.service.status("conversation-1"),
                {"status": "awaiting_approval", "resumable": False},
            )
            tool.assert_not_called()

            resumed = await self.service.approve_purchase(
                "conversation-1",
                pending.approval_id,
                ApprovalDecision(approved=True),
            )

        self.assertEqual(resumed.status, "reply")
        self.assertEqual(resumed.reply, "Purchase complete")
        self.assertIsNone(await self.service.pending_approval("conversation-1"))
        tool.assert_called_once()
        self.assertEqual(
            tool.call_args.args[0].idempotency_key,
            "conversation-1:purchase-1",
        )

    async def test_process_loss_leaves_checkpoint_for_manual_resume(self) -> None:
        started = asyncio.Event()
        never = asyncio.Event()
        attempts = 0

        async def planning(_request):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                started.set()
                await never.wait()
            return LLMResponse(
                message=ChatMessage(role="assistant", content="Recovered reply")
            )

        with patch("graph.agent.call_llm", new=planning):
            running = asyncio.create_task(
                self.service.send_message("conversation-1", "Remember this")
            )
            await asyncio.wait_for(started.wait(), timeout=2)
            await self.service.simulate_crash()
            with self.assertRaises(asyncio.CancelledError):
                await running

            fresh_process = SupportAgentService(self.graph)
            self.assertEqual(
                await fresh_process.status("conversation-1"),
                {"status": "interrupted", "resumable": True},
            )
            transcript = await fresh_process.transcript("conversation-1")
            self.assertEqual(transcript[-1].content, "Remember this")

            result = await fresh_process.resume("conversation-1")

        self.assertEqual(result.reply, "Recovered reply")
        self.assertEqual(attempts, 2)
        self.assertEqual(
            await fresh_process.status("conversation-1"),
            {"status": "idle", "resumable": False},
        )
        with self.assertRaises(TurnNotResumableError):
            await fresh_process.resume("conversation-1")

    async def test_timeout_exhaustion_leaves_a_resumable_checkpoint(self) -> None:
        service = SupportAgentService(
            build_graph(
                InMemorySaver(),
                plan_timeout=timedelta(milliseconds=5),
            )
        )
        await service.create("timed-out", "sa@temporal.io")

        async def never_finishes(_request):
            await asyncio.Event().wait()

        with patch("graph.agent.call_llm", new=never_finishes):
            with self.assertRaises(AgentRunError):
                await service.send_message("timed-out", "Persist this input")

        self.assertEqual(
            await service.status("timed-out"),
            {"status": "interrupted", "resumable": True},
        )
        transcript = await service.transcript("timed-out")
        self.assertEqual(transcript[-1].content, "Persist this input")

    async def test_tools_node_processes_only_one_call_per_invocation(self) -> None:
        calls = [
            ToolCall(id="first", name="search_tracks", args={"query": "one"}),
            ToolCall(id="second", name="search_tracks", args={"query": "two"}),
        ]
        state = {
            "conversation_id": "conversation-1",
            "customer_email": "sa@temporal.io",
            "messages": [
                ChatMessage(role="assistant", tool_calls=calls).model_dump(mode="json")
            ],
            "turn_phase": "running",
        }

        with patch("graph.agent.execute_tool", return_value="found") as tool:
            update = await _execute_tools(state)

        tool.assert_called_once()
        self.assertEqual(tool.call_args.args[0].call.id, "first")
        tool_messages = [
            message
            for message in update["messages"]
            if message["role"] == "tool"
        ]
        self.assertEqual(
            [message["tool_call_id"] for message in tool_messages],
            ["first"],
        )

    def test_retry_policy_excludes_permanent_input_errors(self) -> None:
        self.assertEqual(NODE_RETRY_POLICY.max_attempts, 3)
        self.assertFalse(_retryable(ValueError("bad request")))
        self.assertTrue(_retryable(ConnectionError("provider unavailable")))


if __name__ == "__main__":
    unittest.main()
