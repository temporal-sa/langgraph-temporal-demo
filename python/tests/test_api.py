import unittest
from unittest.mock import AsyncMock, patch

from api import Approve, approve, end_workflow
from models.types import ApprovalDecision
from workflows.agent import SupportAgentWorkflow


class ApproveEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_sends_approval_id_and_decision_as_update_args(self) -> None:
        handle = AsyncMock()

        with patch("api._handle", return_value=handle):
            result = await approve(
                "conversation-id",
                Approve(approvalId="approval-id", approved=True, reason="looks good"),
            )

        self.assertEqual(result, {})
        handle.execute_update.assert_awaited_once_with(
            SupportAgentWorkflow.approve_purchase,
            args=[
                "approval-id",
                ApprovalDecision(approved=True, reason="looks good"),
            ],
        )

    async def test_end_workflow_requests_temporal_cancellation(self) -> None:
        handle = AsyncMock()

        with patch("api._handle", return_value=handle):
            result = await end_workflow("conversation-id")

        self.assertEqual(result, {})
        handle.cancel.assert_awaited_once_with(reason="Ended from demo controls")


if __name__ == "__main__":
    unittest.main()
