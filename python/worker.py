"""Worker entrypoint (slide 34): polls the task queue, runs workflow + activities.

    uv run worker.py

Kill it mid-conversation and restart it — the loop resumes exactly where it
was. That's the crash-recovery demo beat.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor

from temporalio.worker import Worker

import config
from activities.llm import call_llm
from activities.tools import execute_tool
from support_agent_common.demo_controls import run_controlled_worker
from workflows.agent import SupportAgentWorkflow


async def main() -> None:
    client = await config.temporal_client()
    with ThreadPoolExecutor(max_workers=8) as activity_executor:

        def worker_factory() -> Worker:
            return Worker(
                client,
                task_queue=config.TASK_QUEUE,
                workflows=[SupportAgentWorkflow],
                activities=[call_llm, execute_tool],  # async + sync (thread pool)
                activity_executor=activity_executor,
            )

        print(
            f"worker control loop for task queue '{config.TASK_QUEUE}' "
            f"on {config.TEMPORAL_ADDRESS} (provider: {config.LLM_PROVIDER})"
        )
        await run_controlled_worker(
            worker_factory,
            config.DB_URL,
            "temporal",
            initial_failure_rate=config.OPENAI_FAILURE_RATE,
        )


if __name__ == "__main__":
    asyncio.run(main())
