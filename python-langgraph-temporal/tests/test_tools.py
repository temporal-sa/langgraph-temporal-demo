import json
import unittest
from unittest.mock import patch

from activities import tools
from models.types import ToolCall, ToolRequest


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return json.dumps({"result": '[{"TrackId": 1}]'}).encode()


class ToolRoutingTests(unittest.TestCase):
    def test_worker_routes_tools_through_private_backend(self) -> None:
        request = ToolRequest(
            call=ToolCall(id="call-1", name="search_music", args={"query": "jazz"}),
            customer_email="sa@temporal.io",
        )

        with (
            patch.object(tools.config, "BACKEND_URL", "http://backend:8000"),
            patch.object(tools.urllib.request, "urlopen", return_value=FakeResponse()) as urlopen,
        ):
            result = tools.execute_tool(request)

        self.assertEqual(result, '[{"TrackId": 1}]')
        sent_request = urlopen.call_args.args[0]
        self.assertEqual(
            sent_request.full_url,
            "http://backend:8000/internal/tools/execute",
        )

    def test_source_run_without_backend_keeps_local_execution(self) -> None:
        request = ToolRequest(
            call=ToolCall(id="call-1", name="search_music", args={"query": "jazz"}),
            customer_email="sa@temporal.io",
        )
        with (
            patch.object(tools.config, "BACKEND_URL", ""),
            patch.object(tools, "execute_tool_local", return_value="local") as local,
        ):
            result = tools.execute_tool(request)

        self.assertEqual(result, "local")
        local.assert_called_once_with(request)
