import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from graph.agent import build_graph
from models.types import (
    ApprovalDecision,
    ChatMessage,
    LLMResponse,
    PendingPurchase,
    ToolCall,
)


class NativeHitlTests(unittest.IsolatedAsyncioTestCase):
    async def test_purchase_interrupt_resumes_without_custom_routing_state(self) -> None:
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
        app = build_graph().compile(checkpointer=InMemorySaver())
        config = RunnableConfig({"configurable": {"thread_id": "conversation-1"}})

        with (
            patch("graph.agent.call_llm", new=AsyncMock(side_effect=responses)),
            patch("graph.agent.execute_tool", return_value='{"ok": true}') as tool,
        ):
            paused = await app.ainvoke(
                {
                    "conversation_id": "conversation-1",
                    "customer_email": "sa@temporal.io",
                    "messages": [
                        ChatMessage(
                            role="system", content="Help the customer"
                        ).model_dump(mode="json"),
                        ChatMessage(role="user", content="Buy it").model_dump(
                            mode="json"
                        ),
                    ],
                },
                config,
                version="v2",
            )

            self.assertEqual(
                set(paused.value),
                {"conversation_id", "customer_email", "messages"},
            )
            self.assertEqual(len(paused.interrupts), 1)
            pending = PendingPurchase.model_validate(paused.interrupts[0].value)
            self.assertEqual(pending.track_ids, [3])
            tool.assert_not_called()

            resumed = await app.ainvoke(
                Command(
                    resume=ApprovalDecision(approved=True).model_dump(mode="json")
                ),
                config,
                version="v2",
            )

        self.assertEqual(resumed.interrupts, ())
        self.assertEqual(
            ChatMessage.model_validate(resumed.value["messages"][-1]).content,
            "Purchase complete",
        )
        tool.assert_called_once()
        self.assertEqual(
            tool.call_args.args[0].idempotency_key,
            "conversation-1:purchase-1",
        )

    async def test_each_tool_call_runs_in_a_separate_graph_step(self) -> None:
        calls = [
            ToolCall(id="search-1", name="search_music", args={"query": "jazz"}),
            ToolCall(
                id="price-1",
                name="get_track_price",
                args={"track_name": "Blue in Green"},
            ),
        ]
        responses = [
            LLMResponse(message=ChatMessage(role="assistant", tool_calls=calls)),
            LLMResponse(message=ChatMessage(role="assistant", content="Done")),
        ]
        app = build_graph().compile(checkpointer=InMemorySaver())
        config = RunnableConfig({"configurable": {"thread_id": "conversation-2"}})

        with (
            patch("graph.agent.call_llm", new=AsyncMock(side_effect=responses)),
            patch("graph.agent.execute_tool", return_value="[]") as tool,
        ):
            updates = [
                update
                async for update in app.astream(
                    {
                        "conversation_id": "conversation-2",
                        "customer_email": "sa@temporal.io",
                        "messages": [
                            ChatMessage(
                                role="system", content="Help the customer"
                            ).model_dump(mode="json"),
                            ChatMessage(role="user", content="Search").model_dump(
                                mode="json"
                            ),
                        ],
                    },
                    config,
                    stream_mode="updates",
                )
            ]

        tool_updates = [update for update in updates if "tools" in update]
        self.assertEqual(len(tool_updates), 2)
        self.assertEqual(tool.call_count, 2)


if __name__ == "__main__":
    unittest.main()
