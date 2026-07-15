import unittest
from unittest.mock import patch

from fastapi import HTTPException

import api
from support_agent_common.demo_controls import DemoControlState


class DemoControlApiTests(unittest.IsolatedAsyncioTestCase):
    def test_control_payload_exposes_only_langgraph_app_capability(self) -> None:
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
            {"langGraphApp": True, "worker": False, "endWorkflow": False},
        )

    async def test_disabled_app_rejects_conversation_traffic(self) -> None:
        controls = DemoControlState(
            random_openai_failure_rate=0,
            openai_responses_outage=False,
            langgraph_app_enabled=False,
            worker_enabled=True,
        )
        with patch.object(api, "_load_controls", return_value=controls):
            with self.assertRaises(HTTPException) as raised:
                await api._require_app_enabled()

        self.assertEqual(raised.exception.status_code, 503)

    async def test_disabling_app_clears_in_memory_conversations(self) -> None:
        store = api.ConversationStore()
        store.create("conversation", "sa@temporal.io")
        api.app.state.conversations = store
        disabled = DemoControlState(0, False, False, True)

        with patch.object(api, "update_demo_controls", return_value=disabled):
            await api.set_demo_controls(
                api.DemoControlUpdate(langGraphAppEnabled=False)
            )

        with self.assertRaises(KeyError):
            api._store().get("conversation")


if __name__ == "__main__":
    unittest.main()
