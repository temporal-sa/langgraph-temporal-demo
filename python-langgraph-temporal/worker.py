"""Temporal worker for the LangGraph integration variant.

uv run worker.py
"""

import asyncio

from temporalio.contrib.langgraph import LangGraphPlugin
from temporalio.worker import Worker

import config
from graph.agent import GRAPH_NAME, build_graph
from support_agent_common.demo_controls import run_controlled_worker
from workflows.agent import SupportAgentWorkflow


async def main() -> None:
    client = await config.temporal_client()

    def worker_factory() -> Worker:
        plugin = LangGraphPlugin(graphs={GRAPH_NAME: build_graph()})
        return Worker(
            client,
            task_queue=config.TASK_QUEUE,
            workflows=[SupportAgentWorkflow],
            plugins=[plugin],
        )

    print(
        f"worker control loop for task queue '{config.TASK_QUEUE}' on "
        f"{config.TEMPORAL_ADDRESS} (provider: {config.LLM_PROVIDER})"
    )
    await run_controlled_worker(
        worker_factory,
        config.DB_URL,
        "temporal-langgraph",
        initial_failure_rate=config.OPENAI_FAILURE_RATE,
    )


if __name__ == "__main__":
    asyncio.run(main())
