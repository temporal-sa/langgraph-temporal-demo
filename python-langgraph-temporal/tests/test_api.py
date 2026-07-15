import unittest
from unittest.mock import patch

import api
from models.types import PendingPurchase


class FakeHandle:
    def __init__(self) -> None:
        self.update_calls = []
        self.cancel_calls = []

    async def query(self, _query):
        return PendingPurchase(
            approval_id="approval-123", track_ids=[3], description="A track"
        )

    async def execute_update(self, *args, **kwargs):
        self.update_calls.append((args, kwargs))

    async def cancel(self, **kwargs):
        self.cancel_calls.append(kwargs)


class ApiApprovalTests(unittest.IsolatedAsyncioTestCase):
    def test_production_api_routes_are_registered(self) -> None:
        routes = api.app.openapi()["paths"]

        self.assertIn("/api/health", routes)
        self.assertIn("/api/demo/controls", routes)
        self.assertIn("/api/conversations", routes)
        self.assertIn("/api/conversations/{conversation_id}/end", routes)
        self.assertIn("/conversations", routes)

    async def test_pending_approval_includes_opaque_approval_id(self) -> None:
        handle = FakeHandle()
        with patch.object(api, "_handle", return_value=handle):
            response = await api.pending_approval("conversation")

        self.assertEqual(
            response,
            {
                "pending": {
                    "approvalId": "approval-123",
                    "trackIds": [3],
                    "description": "A track",
                }
            },
        )

    async def test_approval_uses_one_atomic_workflow_update(self) -> None:
        handle = FakeHandle()
        body = api.Approve(approvalId="approval-123", approved=True)
        with patch.object(api, "_handle", return_value=handle):
            response = await api.approve("conversation", body)

        self.assertEqual(response, {})
        self.assertEqual(len(handle.update_calls), 1)
        args, kwargs = handle.update_calls[0]
        self.assertEqual(args, (api.SupportAgentWorkflow.approve_purchase,))
        approval_id, decision = kwargs["args"]
        self.assertEqual(approval_id, "approval-123")
        self.assertTrue(decision.approved)

    async def test_end_workflow_requests_temporal_cancellation(self) -> None:
        handle = FakeHandle()
        with patch.object(api, "_handle", return_value=handle):
            response = await api.end_workflow("conversation")

        self.assertEqual(response, {})
        self.assertEqual(
            handle.cancel_calls, [{"reason": "Ended from demo controls"}]
        )
