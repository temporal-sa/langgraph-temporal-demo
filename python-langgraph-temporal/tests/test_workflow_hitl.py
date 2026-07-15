import asyncio
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from temporalio.contrib.langgraph import LangGraphPlugin
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from graph.agent import GRAPH_NAME, build_graph
from models.types import ApprovalDecision, ChatMessage, LLMResponse, ToolCall
from workflows.agent import SupportAgentWorkflow


class TemporalNativeHitlTests(unittest.IsolatedAsyncioTestCase):
    async def test_temporal_plugin_pauses_and_resumes_native_interrupt(self) -> None:
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
        task_queue = f"native-hitl-{uuid4()}"

        with (
            patch("graph.agent.call_llm", new=AsyncMock(side_effect=responses)),
            patch("graph.agent.execute_tool", return_value='{"ok": true}') as tool,
        ):
            async with await WorkflowEnvironment.start_time_skipping() as env:
                async with Worker(
                    env.client,
                    task_queue=task_queue,
                    workflows=[SupportAgentWorkflow],
                    plugins=[LangGraphPlugin(graphs={GRAPH_NAME: build_graph()})],
                ):
                    handle = await env.client.start_workflow(
                        SupportAgentWorkflow.run,
                        "sa@temporal.io",
                        id=f"native-hitl-{uuid4()}",
                        task_queue=task_queue,
                    )
                    paused = await handle.execute_update(
                        SupportAgentWorkflow.send_message,
                        "Buy it",
                    )
                    pending = await handle.query(
                        SupportAgentWorkflow.pending_approval
                    )

                    self.assertEqual(paused.status, "awaiting_approval")
                    self.assertIsNotNone(pending)
                    assert pending is not None
                    self.assertEqual(pending.track_ids, [3])
                    tool.assert_not_called()

                    await handle.execute_update(
                        SupportAgentWorkflow.approve_purchase,
                        args=[pending.approval_id, ApprovalDecision(approved=True)],
                    )

                    transcript = []
                    for _ in range(50):
                        transcript = await handle.query(
                            SupportAgentWorkflow.transcript
                        )
                        if any(
                            message.content == "Purchase complete"
                            for message in transcript
                        ):
                            break
                        await asyncio.sleep(0.02)

                    await handle.cancel()

        self.assertTrue(
            any(message.content == "Purchase complete" for message in transcript)
        )
        tool.assert_called_once()


if __name__ == "__main__":
    unittest.main()
