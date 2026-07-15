import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from activities.llm import _call_openai
from models.types import ChatMessage, LLMRequest, ToolCall


class ResponseItem(SimpleNamespace):
    def model_dump(self, *, mode, exclude_none):
        self.test_case.assertEqual(mode, "json")
        self.test_case.assertTrue(exclude_none)
        return self.payload


class OpenAIResponsesTests(unittest.IsolatedAsyncioTestCase):
    async def test_preserves_reasoning_and_maps_function_calls(self) -> None:
        prior_reasoning = {
            "id": "rs_previous",
            "type": "reasoning",
            "encrypted_content": "opaque",
            "summary": [],
        }
        prior_call = {
            "type": "function_call",
            "call_id": "call_previous",
            "name": "search_music",
            "arguments": '{"query":"Miles Davis"}',
        }
        next_reasoning = {
            "id": "rs_next",
            "type": "reasoning",
            "encrypted_content": "also-opaque",
            "summary": [],
        }
        next_call = {
            "type": "function_call",
            "call_id": "call_next",
            "name": "get_track_price",
            "arguments": '{"track_name":"So What"}',
        }
        output = [
            ResponseItem(test_case=self, payload=next_reasoning, type="reasoning"),
            ResponseItem(
                test_case=self,
                payload=next_call,
                type="function_call",
                call_id="call_next",
                name="get_track_price",
                arguments='{"track_name":"So What"}',
            ),
        ]
        response = SimpleNamespace(output=output, output_text="I found it.")
        create = AsyncMock(return_value=response)
        client = SimpleNamespace(responses=SimpleNamespace(create=create))
        request = LLMRequest(messages=[
            ChatMessage(role="system", content="Help the customer."),
            ChatMessage(role="user", content="Find Miles Davis."),
            ChatMessage(
                role="assistant",
                tool_calls=[ToolCall(
                    id="call_previous",
                    name="search_music",
                    args={"query": "Miles Davis"},
                )],
                provider_items=[prior_reasoning, prior_call],
            ),
            ChatMessage(
                role="tool",
                tool_call_id="call_previous",
                content='[{"track":"So What"}]',
            ),
        ])

        with patch("activities.llm.openai.AsyncOpenAI", return_value=client):
            result = await _call_openai(request)

        create.assert_awaited_once()
        kwargs = create.await_args.kwargs
        self.assertFalse(kwargs["store"])
        self.assertEqual(kwargs["include"], ["reasoning.encrypted_content"])
        self.assertEqual(kwargs["input"][2:4], [prior_reasoning, prior_call])
        self.assertEqual(kwargs["input"][4], {
            "type": "function_call_output",
            "call_id": "call_previous",
            "output": '[{"track":"So What"}]',
        })
        self.assertNotIn("function", kwargs["tools"][0])
        self.assertFalse(kwargs["tools"][0]["strict"])

        self.assertEqual(result.message.content, "I found it.")
        self.assertEqual(result.message.tool_calls, [ToolCall(
            id="call_next",
            name="get_track_price",
            args={"track_name": "So What"},
        )])
        self.assertEqual(result.message.provider_items, [next_reasoning, next_call])


if __name__ == "__main__":
    unittest.main()
