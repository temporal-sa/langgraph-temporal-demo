"""Optional CLI: start or continue a Temporal + LangGraph conversation.

    uv run starter.py                       # starts a conversation, then REPL
    uv run starter.py <conversation-id>     # continue an existing one
"""

import asyncio
import secrets
import sys

import config
from models.types import TurnResult
from workflows.agent import SupportAgentWorkflow


async def main() -> None:
    client = await config.temporal_client()

    if len(sys.argv) > 1:
        conversation_id = sys.argv[1]
        handle = client.get_workflow_handle_for(SupportAgentWorkflow.run, conversation_id)
    else:
        conversation_id = f"support-cli-{secrets.token_hex(2)}"
        handle = await client.start_workflow(
            SupportAgentWorkflow.run,
            "sa@temporal.io",
            id=conversation_id,
            task_queue=config.TASK_QUEUE,
        )
    print(f"conversation: {conversation_id}  (Ctrl-C to exit; workflow keeps running)")

    while True:
        text = input("you> ").strip()
        if not text:
            continue
        result: TurnResult = await handle.execute_update(
            SupportAgentWorkflow.send_message, text
        )
        print(f"agent> {result.reply}")
        if result.status == "awaiting_approval":
            print(f"purchase awaiting approval: uv run approve.py {conversation_id}")


if __name__ == "__main__":
    asyncio.run(main())
