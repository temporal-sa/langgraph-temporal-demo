"""Shared, durable fault-injection controls for the demo runtimes."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import random
from typing import Protocol

import psycopg
from psycopg.rows import dict_row


@dataclass(frozen=True)
class DemoControlState:
    random_openai_failure_rate: float
    openai_responses_outage: bool
    langgraph_app_enabled: bool
    worker_enabled: bool


class DemoOpenAIError(RuntimeError):
    """Base class for intentional OpenAI failures triggered by the demo UI."""


class DemoOpenAIRandomFailure(DemoOpenAIError):
    pass


class DemoOpenAIResponsesOutage(DemoOpenAIError):
    pass


class ControlledWorker(Protocol):
    async def run(self) -> None: ...

    async def shutdown(self) -> None: ...


def _initialize(conn, backend: str, initial_failure_rate: float) -> None:
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtext('support-agent-demo-controls'))"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS demo_control (
            backend text PRIMARY KEY,
            random_openai_failure_rate double precision NOT NULL DEFAULT 0,
            openai_responses_outage boolean NOT NULL DEFAULT false,
            langgraph_app_enabled boolean NOT NULL DEFAULT true,
            worker_enabled boolean NOT NULL DEFAULT true,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CHECK (random_openai_failure_rate >= 0),
            CHECK (random_openai_failure_rate <= 1)
        )
        """
    )
    conn.execute(
        """
        ALTER TABLE demo_control
        ADD COLUMN IF NOT EXISTS langgraph_app_enabled boolean NOT NULL DEFAULT true
        """
    )
    conn.execute(
        """
        ALTER TABLE demo_control
        ADD COLUMN IF NOT EXISTS worker_enabled boolean NOT NULL DEFAULT true
        """
    )
    conn.execute(
        """
        INSERT INTO demo_control (backend, random_openai_failure_rate)
        VALUES (%s, %s)
        ON CONFLICT (backend) DO NOTHING
        """,
        (backend, initial_failure_rate),
    )


def _state(row) -> DemoControlState:
    return DemoControlState(
        random_openai_failure_rate=float(row["random_openai_failure_rate"]),
        openai_responses_outage=bool(row["openai_responses_outage"]),
        langgraph_app_enabled=bool(row["langgraph_app_enabled"]),
        worker_enabled=bool(row["worker_enabled"]),
    )


def get_demo_controls(
    db_url: str, backend: str, *, initial_failure_rate: float = 0
) -> DemoControlState:
    with psycopg.connect(db_url, row_factory=dict_row) as conn:
        _initialize(conn, backend, initial_failure_rate)
        row = conn.execute(
            """
            SELECT random_openai_failure_rate, openai_responses_outage,
                   langgraph_app_enabled, worker_enabled
            FROM demo_control
            WHERE backend = %s
            """,
            (backend,),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"demo controls were not initialized for {backend}")
        return _state(row)


def update_demo_controls(
    db_url: str,
    backend: str,
    *,
    random_openai_failure_rate: float | None = None,
    openai_responses_outage: bool | None = None,
    langgraph_app_enabled: bool | None = None,
    worker_enabled: bool | None = None,
    initial_failure_rate: float = 0,
) -> DemoControlState:
    if random_openai_failure_rate is not None and not (
        0 <= random_openai_failure_rate <= 1
    ):
        raise ValueError("random OpenAI failure rate must be between 0 and 1")

    with psycopg.connect(db_url, row_factory=dict_row) as conn:
        _initialize(conn, backend, initial_failure_rate)
        row = conn.execute(
            """
            UPDATE demo_control
            SET random_openai_failure_rate = coalesce(%s, random_openai_failure_rate),
                openai_responses_outage = coalesce(%s, openai_responses_outage),
                langgraph_app_enabled = coalesce(%s, langgraph_app_enabled),
                worker_enabled = coalesce(%s, worker_enabled),
                updated_at = now()
            WHERE backend = %s
            RETURNING random_openai_failure_rate, openai_responses_outage,
                      langgraph_app_enabled, worker_enabled
            """,
            (
                random_openai_failure_rate,
                openai_responses_outage,
                langgraph_app_enabled,
                worker_enabled,
                backend,
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"demo controls were not initialized for {backend}")
        return _state(row)


def maybe_raise_openai_failure(
    db_url: str,
    backend: str,
    *,
    initial_failure_rate: float = 0,
    random_value: Callable[[], float] = random.random,
) -> None:
    controls = get_demo_controls(
        db_url, backend, initial_failure_rate=initial_failure_rate
    )
    if controls.openai_responses_outage:
        raise DemoOpenAIResponsesOutage(
            "Simulated OpenAI Responses API outage. Disable it in Demo controls to resume."
        )
    if (
        controls.random_openai_failure_rate > 0
        and random_value() < controls.random_openai_failure_rate
    ):
        raise DemoOpenAIRandomFailure(
            "Simulated random OpenAI failure "
            f"(rate={controls.random_openai_failure_rate:g})."
        )


async def run_controlled_worker(
    worker_factory: Callable[[], ControlledWorker],
    db_url: str,
    backend: str,
    *,
    initial_failure_rate: float = 0,
    poll_interval: float = 1,
) -> None:
    """Start and stop a Temporal poller as the demo checkbox changes."""

    worker: ControlledWorker | None = None
    worker_task: asyncio.Task[None] | None = None
    try:
        while True:
            try:
                controls = await asyncio.to_thread(
                    get_demo_controls,
                    db_url,
                    backend,
                    initial_failure_rate=initial_failure_rate,
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                print(f"demo controls unavailable; worker state unchanged: {error}")
                await asyncio.sleep(poll_interval)
                continue

            if controls.worker_enabled and worker_task is None:
                worker = worker_factory()
                worker_task = asyncio.create_task(worker.run())
                print(f"demo controls enabled the {backend} worker poller")
            elif not controls.worker_enabled and worker_task is not None:
                assert worker is not None
                print(f"demo controls disabled the {backend} worker poller")
                await worker.shutdown()
                await worker_task
                worker = None
                worker_task = None

            if worker_task is not None and worker_task.done():
                await worker_task
                worker = None
                worker_task = None

            await asyncio.sleep(poll_interval)
    finally:
        if worker is not None and worker_task is not None:
            await worker.shutdown()
            await worker_task
