"""Temporal worker for the LangGraph integration variant.

    uv run worker.py
"""

import asyncio

from temporalio.contrib.langgraph import LangGraphPlugin
from temporalio.worker import Worker

import config
from graph.agent import GRAPH_NAME, build_graph
from workflows.agent import SupportAgentWorkflow


async def main() -> None:
    client = await config.temporal_client()
    plugin = LangGraphPlugin(graphs={GRAPH_NAME: build_graph()})
    worker = Worker(
        client,
        task_queue=config.TASK_QUEUE,
        workflows=[SupportAgentWorkflow],
        plugins=[plugin],
    )
    print(
        f"worker polling task queue '{config.TASK_QUEUE}' on "
        f"{config.TEMPORAL_ADDRESS} (provider: {config.LLM_PROVIDER})"
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
