"""Optional CLI for the Postgres-checkpointed standalone LangGraph agent.

    uv run starter.py
"""

import asyncio

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

import config
from checkpointing import strict_checkpoint_serializer
from graph.agent import SupportAgentService, build_graph
from models.types import ApprovalDecision
from support_agent_common.conversations import new_conversation_id


async def main() -> None:
    async with AsyncPostgresSaver.from_conn_string(
        config.DB_URL,
        serde=strict_checkpoint_serializer(),
    ) as checkpointer:
        await checkpointer.setup()
        service = SupportAgentService(build_graph(checkpointer))
        conversation_id = new_conversation_id("sa@example.com")
        await service.create(conversation_id, "sa@example.com")
        print(f"conversation: {conversation_id}  (Ctrl-C to exit)")

        while True:
            text = input("you> ").strip()
            if not text:
                continue

            result = await service.send_message(conversation_id, text)
            print(f"agent> {result.reply}")

            while result.status == "awaiting_approval":
                pending = await service.pending_approval(conversation_id)
                description = pending.description if pending else "purchase"
                answer = input(f"approve {description}? [Y/n] ").strip().lower()
                approved = answer not in {"n", "no", "reject"}
                if pending is None:
                    raise RuntimeError("purchase approval disappeared")
                result = await service.approve_purchase(
                    conversation_id,
                    pending.approval_id,
                    ApprovalDecision(approved=approved),
                )
                print(f"agent> {result.reply}")


if __name__ == "__main__":
    asyncio.run(main())
