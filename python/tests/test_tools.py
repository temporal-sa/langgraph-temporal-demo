import unittest
from unittest.mock import patch

from activities import tools
from models.types import ToolCall, ToolRequest


class PurchaseToolTests(unittest.TestCase):
    def test_purchase_passes_idempotency_key_to_database(self) -> None:
        request = ToolRequest(
            call=ToolCall(
                id="purchase-1",
                name="purchase_tracks",
                args={"track_ids": [3]},
            ),
            customer_email="sa@temporal.io",
            idempotency_key="workflow-1:purchase-1",
        )

        with patch.object(tools.db, "record_purchase", return_value={}) as purchase:
            tools.execute_tool(request)

        purchase.assert_called_once_with(
            "sa@temporal.io",
            [3],
            idempotency_key="workflow-1:purchase-1",
        )


if __name__ == "__main__":
    unittest.main()
