import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException

import api
from graph.agent import (
    SupportAgentService,
    TurnNotResumableError,
    UnknownConversationError,
)
from models.types import TurnResult
from support_agent_common.demo_controls import DemoControlState


class DemoControlApiTests(unittest.IsolatedAsyncioTestCase):
    def test_control_payload_exposes_app_and_manual_resume(self) -> None:
        payload = api._control_payload(
            DemoControlState(
                random_openai_failure_rate=0.5,
                openai_responses_outage=False,
                langgraph_app_enabled=True,
                worker_enabled=True,
            )
        )

        self.assertTrue(payload["randomOpenAIFailures"])
        self.assertEqual(
            payload["capabilities"],
            {
                "langGraphApp": True,
                "worker": False,
                "resumeTurn": True,
                "endWorkflow": False,
            },
        )

    async def test_disabled_app_rejects_conversation_traffic(self) -> None:
        controls = DemoControlState(0, False, False, True)
        with patch.object(api, "_load_controls", return_value=controls):
            with self.assertRaises(HTTPException) as raised:
                await api._require_app_enabled()

        self.assertEqual(raised.exception.status_code, 503)

    async def test_disable_then_enable_rebuilds_runner_over_same_graph(self) -> None:
        old_agent = AsyncMock(spec=SupportAgentService)
        graph = Mock()
        api.app.state.agent = old_agent
        api.app.state.graph = graph
        disabled = DemoControlState(0, False, False, True)

        with patch.object(api, "update_demo_controls", return_value=disabled):
            await api.set_demo_controls(
                api.DemoControlUpdate(langGraphAppEnabled=False)
            )

        old_agent.simulate_crash.assert_awaited_once()
        self.assertIsNone(api.app.state.agent)

        enabled = DemoControlState(0, False, True, True)
        with patch.object(api, "update_demo_controls", return_value=enabled):
            await api.set_demo_controls(
                api.DemoControlUpdate(langGraphAppEnabled=True)
            )

        self.assertIsInstance(api.app.state.agent, SupportAgentService)
        self.assertIs(api.app.state.agent._graph, graph)

    async def test_status_and_resume_delegate_to_checkpoint_service(self) -> None:
        agent = AsyncMock(spec=SupportAgentService)
        agent.status.return_value = {"status": "interrupted", "resumable": True}
        agent.resume.return_value = TurnResult(status="reply", reply="Recovered")
        with (
            patch.object(api, "_require_app_enabled", new=AsyncMock()),
            patch.object(api, "_agent", return_value=agent),
        ):
            status = await api.conversation_status("conversation-1")
            result = await api.resume("conversation-1")

        self.assertEqual(status["status"], "interrupted")
        self.assertEqual(result, {"status": "reply", "reply": "Recovered"})
        agent.status.assert_awaited_once_with("conversation-1")
        agent.resume.assert_awaited_once_with("conversation-1")

    def test_invalid_resume_maps_to_conflict(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            api._raise_agent_error(TurnNotResumableError("nothing to resume"))
        self.assertEqual(raised.exception.status_code, 409)

    def test_unknown_conversation_maps_to_not_found(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            api._raise_agent_error(UnknownConversationError("unknown"))
        self.assertEqual(raised.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
