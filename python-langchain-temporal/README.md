# Support Agent with Temporal + LangGraph

This folder runs the music-store support agent with Temporal's LangGraph
integration. The agent graph is a LangGraph `StateGraph`; the worker registers it
with `temporalio.contrib.langgraph.LangGraphPlugin`, and the Workflow invokes it
with `temporalio.contrib.langgraph.graph(...)`.

The HTTP contract matches the other demo backends.

## Run

Use separate terminals from the repository root.

Start Postgres:

```bash
docker compose up -d
```

Start Temporal:

```bash
temporal server start-dev --ui-port 8233
```

Start the Temporal + LangGraph worker:

```bash
cd python-langchain-temporal
uv run worker.py
```

Start the HTTP API:

```bash
cd python-langchain-temporal
uv run uvicorn api:app --port 8002
```

Point the web UI at the `temporal-langgraph` backend preset, or open:

```text
http://localhost:5173?backend=temporal-langgraph
```

## Configuration

Use the same repo-root `.env` values as the original demo:

- `TEMPORAL_ADDRESS`
- `TEMPORAL_NAMESPACE`
- `TEMPORAL_API_KEY`, `TEMPORAL_TLS_CERT`, `TEMPORAL_TLS_KEY` for Temporal Cloud
- `LANGGRAPH_TEMPORAL_TASK_QUEUE` to override the default task queue
- `DB_URL`
- `LLM_PROVIDER=anthropic` or `LLM_PROVIDER=openai`
- `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`
- `ANTHROPIC_MODEL`
- `OPENAI_MODEL`
- `OPENAI_FAILURE_RATE` to simulate retryable OpenAI planning failures

Default task queue:

```text
support-agent-temporal-langgraph
```

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

## Simulate OpenAI API Failures

`OPENAI_FAILURE_RATE` is checked inside the LangGraph `plan` node. Because that
node runs as a Temporal Activity, simulated failures are retryable Temporal
Activity failures.

Fail 20% of OpenAI planning calls:

```bash
LLM_PROVIDER=openai OPENAI_FAILURE_RATE=0.2 uv run worker.py
```

Disable simulated failures:

```bash
OPENAI_FAILURE_RATE=0 uv run worker.py
```
