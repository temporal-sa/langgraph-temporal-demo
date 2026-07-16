# Support Agent with LangGraph

This folder is the self-hosted standalone LangGraph version of the music-store
support agent. LangGraph runs the ReAct loop in the FastAPI process and stores
thread checkpoints in Postgres through `AsyncPostgresSaver`.

## Run

From this folder:

```bash
cd ..
docker compose up -d
cd python-langgraph
uv run starter.py
```

For the HTTP API:

```bash
cd ..
docker compose up -d
cd python-langgraph
uv run uvicorn api:app --port 8001
```

Point the web UI at `http://localhost:8001` if you want to use the existing
browser chat frontend.

## Docker Operations

The music catalog and customer data live in the Postgres container defined in
`../docker-compose.yml`. Run these commands from the repository root.

Start the database:

```bash
docker compose up -d
```

Check status:

```bash
docker compose ps postgres
```

View database logs:

```bash
docker compose logs -f postgres
```

Stop the database without deleting data:

```bash
docker compose stop postgres
```

Start it again after stopping:

```bash
docker compose start postgres
```

Stop and remove the container:

```bash
docker compose down
```

Reset the database to the seed SQL files:

```bash
docker compose down -v
docker compose up -d
```

Pull the latest `postgres:16` image:

```bash
docker compose pull postgres
```

Remove the local `postgres:16` image after the container is stopped:

```bash
docker image rm postgres:16
```

## Configuration

Use the same repo-root `.env` values as the original demo:

- `LLM_PROVIDER=anthropic` or `LLM_PROVIDER=openai`
- `ANTHROPIC_MODEL`
- `OPENAI_MODEL`
- `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`
- `DB_URL`
- `OPENAI_FAILURE_RATE` to simulate OpenAI API failures when `LLM_PROVIDER=openai`

Conversation and interrupt state survive API restarts. Active execution does
not: a process that disappears mid-node leaves a resumable checkpoint with no
runner. `POST /conversations/{id}/resume` explicitly continues that thread.

## Persistence is not a scheduler

The graph uses native LangGraph retry policies and node timeouts. While the API
process is alive, transient plan/tool failures are retried up to three times.
If the process dies, Postgres still contains the last checkpoint, but no
external service automatically invokes the graph again. The status endpoint
reports that distinction:

```text
GET  /conversations/{id}/status  -> idle | running | awaiting_approval | interrupted
POST /conversations/{id}/resume  -> explicitly invoke an interrupted thread
```

This is a comparison with self-hosted open-source LangGraph, not LangGraph
Platform. LangSmith tracing can provide LangGraph attempt observability when it
is configured; Temporal's comparison point is its service-owned event history,
task queues, and automatic worker recovery.

## Human approval

Purchases use [LangGraph's native human-in-the-loop API][langgraph-interrupts].
The tools node calls `interrupt()` with a JSON-serializable purchase request,
and the approval endpoint resumes the same Postgres-backed LangGraph thread
with `Command(resume=...)`.

The graph executes one tool call per `tools` node invocation. Purchase requests
also carry an idempotency key derived from the conversation ID and tool-call ID,
so a repeated execution reads the original invoice instead of inserting a
second purchase.

Temporal Activities are also at-least-once, so both implementations must make
external writes idempotent. Temporal owns durable retry scheduling and attempt
history; it does not make a database insert exactly-once by itself.

[langgraph-interrupts]: https://docs.langchain.com/oss/python/langgraph/interrupts

## Simulate OpenAI API Failures

Set `OPENAI_FAILURE_RATE` when starting the app to randomly fail OpenAI planning
calls before the real API request is sent. The value must be between `0` and `1`.

Fail 20% of OpenAI calls:

```bash
LLM_PROVIDER=openai OPENAI_FAILURE_RATE=0.2 uv run uvicorn api:app --port 8001
```

Fail every OpenAI call:

```bash
LLM_PROVIDER=openai OPENAI_FAILURE_RATE=1 uv run uvicorn api:app --port 8001
```

Disable simulated failures:

```bash
OPENAI_FAILURE_RATE=0 uv run uvicorn api:app --port 8001
```
