import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from support_agent_common import database
from support_agent_common.conversations import new_conversation_id
from support_agent_common.demo_controls import (
    DemoControlState,
    DemoOpenAIRandomFailure,
    DemoOpenAIResponsesOutage,
    maybe_raise_openai_failure,
    run_controlled_worker,
)


class ConversationIdTests(unittest.TestCase):
    def test_ids_are_opaque_and_collision_resistant(self) -> None:
        ids = {new_conversation_id("sa@temporal.io") for _ in range(100)}

        self.assertEqual(len(ids), 100)
        self.assertTrue(
            all(value.startswith("support-sa-temporal-io-") for value in ids)
        )
        prefix = "support-sa-temporal-io-"
        self.assertTrue(all(len(value.removeprefix(prefix)) >= 22 for value in ids))


class CatalogQueryTests(unittest.TestCase):
    def test_genre_search_joins_genre_and_parameterizes_input(self) -> None:
        calls: list[tuple[str, dict[str, object]]] = []

        class Cursor:
            def fetchall(self):
                return [{"track": "Rock Song"}]

        class Connection:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, sql, params):
                calls.append((sql, params))
                return Cursor()

        with patch("support_agent_common.database._connect", return_value=Connection()):
            result = database.search_music_by_genre("postgresql://demo", "Rock")

        self.assertEqual(result, [{"track": "Rock Song"}])
        self.assertIn("JOIN genre g", calls[0][0])
        self.assertIn("g.name ILIKE %(q)s", calls[0][0])
        self.assertEqual(calls[0][1], {"q": "%Rock%"})


class DemoControlTests(unittest.TestCase):
    def test_forced_outage_takes_precedence_over_random_failures(self) -> None:
        controls = DemoControlState(
            random_openai_failure_rate=1,
            openai_responses_outage=True,
            langgraph_app_enabled=True,
            worker_enabled=True,
        )
        with patch(
            "support_agent_common.demo_controls.get_demo_controls",
            return_value=controls,
        ):
            with self.assertRaises(DemoOpenAIResponsesOutage):
                maybe_raise_openai_failure("postgresql://demo", "temporal")

    def test_random_failure_uses_runtime_rate(self) -> None:
        controls = DemoControlState(
            random_openai_failure_rate=0.5,
            openai_responses_outage=False,
            langgraph_app_enabled=True,
            worker_enabled=True,
        )
        with patch(
            "support_agent_common.demo_controls.get_demo_controls",
            return_value=controls,
        ):
            with self.assertRaises(DemoOpenAIRandomFailure):
                maybe_raise_openai_failure(
                    "postgresql://demo", "temporal", random_value=lambda: 0.25
                )


class ControlledWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_poller_stops_when_checkbox_is_disabled(self) -> None:
        enabled = DemoControlState(0, False, True, True)
        disabled = DemoControlState(0, False, True, False)
        workers = []

        class FakeWorker:
            def __init__(self) -> None:
                self.stopped = asyncio.Event()
                self.shutdown_count = 0

            async def run(self) -> None:
                await self.stopped.wait()

            async def shutdown(self) -> None:
                self.shutdown_count += 1
                self.stopped.set()

        def worker_factory():
            worker = FakeWorker()
            workers.append(worker)
            return worker

        class StopLoop(RuntimeError):
            pass

        with (
            patch(
                "support_agent_common.demo_controls.get_demo_controls",
                side_effect=[enabled, disabled],
            ),
            patch(
                "support_agent_common.demo_controls.asyncio.sleep",
                new=AsyncMock(side_effect=[None, StopLoop()]),
            ),
        ):
            with self.assertRaises(StopLoop):
                await run_controlled_worker(
                    worker_factory,
                    "postgresql://demo",
                    "temporal",
                    poll_interval=0,
                )

        self.assertEqual(len(workers), 1)
        self.assertEqual(workers[0].shutdown_count, 1)
