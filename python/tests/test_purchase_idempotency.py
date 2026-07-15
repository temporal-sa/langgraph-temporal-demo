import unittest
from decimal import Decimal
from unittest.mock import patch

from support_agent_common import database


class Cursor:
    def __init__(self, *, one=None, all_rows=None) -> None:
        self.one = one
        self.all_rows = all_rows or []

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.all_rows


class Connection:
    def __init__(self, results) -> None:
        self.results = iter(results)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return next(self.results)


class PurchaseIdempotencyTests(unittest.TestCase):
    def test_retry_reads_existing_invoice_without_inserting_purchase(self) -> None:
        connection = Connection(
            [
                Cursor(),
                Cursor(),
                Cursor(one=None),
                Cursor(one={"invoice_id": 42}),
                Cursor(
                    all_rows=[
                        {
                            "invoice_id": 42,
                            "total": Decimal("0.99"),
                            "track_id": 3,
                            "name": "Blue in Green",
                            "unit_price": Decimal("0.99"),
                        }
                    ]
                ),
            ]
        )

        with patch.object(database, "_connect", return_value=connection):
            result = database.record_purchase(
                "postgresql://demo",
                "sa@temporal.io",
                [3],
                idempotency_key="workflow-1:purchase-1",
            )

        self.assertEqual(result["invoice_id"], 42)
        self.assertEqual(result["tracks"][0]["track_id"], 3)
        sql = "\n".join(call[0] for call in connection.calls)
        self.assertIn("ON CONFLICT (idempotency_key) DO NOTHING", sql)
        self.assertNotIn("INSERT INTO invoice (", sql)

    def test_new_purchase_reserves_key_and_serializes_id_allocation(self) -> None:
        connection = Connection(
            [
                Cursor(),
                Cursor(),
                Cursor(one={"idempotency_key": "workflow-1:purchase-1"}),
                Cursor(
                    one={
                        "customer_id": 1,
                        "address": "1 Main St",
                        "city": "Seattle",
                        "state": "WA",
                        "country": "USA",
                        "postal_code": "98101",
                    }
                ),
                Cursor(
                    all_rows=[
                        {
                            "track_id": 3,
                            "name": "Blue in Green",
                            "unit_price": Decimal("0.99"),
                        }
                    ]
                ),
                Cursor(one={"id": 43}),
                Cursor(),
                Cursor(one={"id": 100}),
                Cursor(),
                Cursor(),
            ]
        )

        with patch.object(database, "_connect", return_value=connection):
            result = database.record_purchase(
                "postgresql://demo",
                "sa@temporal.io",
                [3],
                idempotency_key="workflow-1:purchase-1",
            )

        self.assertEqual(result["invoice_id"], 43)
        sql = "\n".join(call[0] for call in connection.calls)
        self.assertIn("pg_advisory_xact_lock", sql)
        self.assertIn("INSERT INTO invoice (", sql)
        self.assertIn("UPDATE purchase_idempotency SET invoice_id", sql)


if __name__ == "__main__":
    unittest.main()
