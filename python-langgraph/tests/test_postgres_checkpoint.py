import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

import config
from checkpointing import strict_checkpoint_serializer
from graph.agent import SupportAgentService, build_graph
from models.types import ApprovalDecision, ChatMessage, LLMResponse, ToolCall


@unittest.skipUnless(
    os.getenv("RUN_POSTGRES_INTEGRATION") == "1",
    "set RUN_POSTGRES_INTEGRATION=1 with Postgres running",
)
class PostgresCheckpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_completed_conversation_survives_new_connection(self) -> None:
        conversation_id = f"checkpoint-complete-{uuid4()}"
        try:
            async with self._saver() as saver:
                await saver.setup()
                service = SupportAgentService(build_graph(saver))
                await service.create(conversation_id, "sa@temporal.io")
                with patch(
                    "graph.agent.call_llm",
                    new=AsyncMock(
                        return_value=LLMResponse(
                            message=ChatMessage(role="assistant", content="Durable")
                        )
                    ),
                ):
                    await service.send_message(conversation_id, "Remember me")

            async with self._saver() as saver:
                fresh = SupportAgentService(build_graph(saver))
                transcript = await fresh.transcript(conversation_id)
                self.assertEqual(
                    [message.content for message in transcript],
                    ["Remember me", "Durable"],
                )
                self.assertEqual(
                    await fresh.status(conversation_id),
                    {"status": "idle", "resumable": False},
                )
        finally:
            await self._delete(conversation_id)

    async def test_pending_interrupt_survives_and_resumes_on_new_connection(
        self,
    ) -> None:
        conversation_id = f"checkpoint-approval-{uuid4()}"
        purchase = ToolCall(
            id="purchase-1",
            name="purchase_tracks",
            args={"track_ids": [3], "summary": "One track"},
        )
        try:
            async with self._saver() as saver:
                await saver.setup()
                service = SupportAgentService(build_graph(saver))
                await service.create(conversation_id, "sa@temporal.io")
                with patch(
                    "graph.agent.call_llm",
                    new=AsyncMock(
                        return_value=LLMResponse(
                            message=ChatMessage(role="assistant", tool_calls=[purchase])
                        )
                    ),
                ):
                    await service.send_message(conversation_id, "Buy it")

            async with self._saver() as saver:
                fresh = SupportAgentService(build_graph(saver))
                pending = await fresh.pending_approval(conversation_id)
                self.assertIsNotNone(pending)
                assert pending is not None
                with (
                    patch(
                        "graph.agent.call_llm",
                        new=AsyncMock(
                            return_value=LLMResponse(
                                message=ChatMessage(
                                    role="assistant", content="Purchase complete"
                                )
                            )
                        ),
                    ),
                    patch("graph.agent.execute_tool", return_value='{"ok": true}'),
                ):
                    result = await fresh.approve_purchase(
                        conversation_id,
                        pending.approval_id,
                        ApprovalDecision(approved=True),
                    )
                self.assertEqual(result.reply, "Purchase complete")
        finally:
            await self._delete(conversation_id)

    async def test_killed_turn_is_persisted_but_not_automatically_running(self) -> None:
        conversation_id = f"checkpoint-interrupted-{uuid4()}"
        started = asyncio.Event()
        never = asyncio.Event()

        async def blocked(_request):
            started.set()
            await never.wait()

        try:
            async with self._saver() as saver:
                await saver.setup()
                service = SupportAgentService(build_graph(saver))
                await service.create(conversation_id, "sa@temporal.io")
                with patch("graph.agent.call_llm", new=blocked):
                    running = asyncio.create_task(
                        service.send_message(conversation_id, "Finish after restart")
                    )
                    await asyncio.wait_for(started.wait(), timeout=2)
                    await service.simulate_crash()
                    with self.assertRaises(asyncio.CancelledError):
                        await running

            async with self._saver() as saver:
                fresh = SupportAgentService(build_graph(saver))
                self.assertEqual(
                    await fresh.status(conversation_id),
                    {"status": "interrupted", "resumable": True},
                )
                await asyncio.sleep(0.05)
                self.assertEqual(
                    await fresh.status(conversation_id),
                    {"status": "interrupted", "resumable": True},
                )
                with patch(
                    "graph.agent.call_llm",
                    new=AsyncMock(
                        return_value=LLMResponse(
                            message=ChatMessage(role="assistant", content="Recovered")
                        )
                    ),
                ):
                    result = await fresh.resume(conversation_id)
                self.assertEqual(result.reply, "Recovered")
        finally:
            await self._delete(conversation_id)

    async def _delete(self, conversation_id: str) -> None:
        async with self._saver() as saver:
            await saver.adelete_thread(conversation_id)

    @staticmethod
    def _saver():
        return AsyncPostgresSaver.from_conn_string(
            config.DB_URL,
            serde=strict_checkpoint_serializer(),
        )


if __name__ == "__main__":
    unittest.main()
