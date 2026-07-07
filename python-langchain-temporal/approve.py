"""Optional CLI: approve or reject a pending purchase through Temporal.

    uv run approve.py <conversation-id>            # approve
    uv run approve.py <conversation-id> --reject   # reject
"""

import asyncio
import sys

import config
from models.types import ApprovalDecision
from workflows.agent import SupportAgentWorkflow


async def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("usage: uv run approve.py <conversation-id> [--reject]")
    conversation_id = sys.argv[1]
    approved = "--reject" not in sys.argv

    client = await config.temporal_client()
    handle = client.get_workflow_handle_for(SupportAgentWorkflow.run, conversation_id)
    await handle.signal(
        SupportAgentWorkflow.approve_purchase, ApprovalDecision(approved=approved)
    )
    print(f"{'approved' if approved else 'rejected'} -> signal sent to {conversation_id}")


if __name__ == "__main__":
    asyncio.run(main())
