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
docker compose up -d postgres
```

Start Temporal:

```bash
temporal server start-dev --ui-port 8233
```

Start the Temporal + LangGraph worker:

```bash
cd python-langgraph-temporal
uv run python worker.py
```

Start the HTTP API:

```bash
cd python-langgraph-temporal
uv run python -m uvicorn api:app --port 8002
```

Point the web UI at the `temporal-langgraph` backend preset, or open:

```text
http://localhost:5173?backend=temporal-langgraph
```

## Configuration

Use the same repo-root `.env` values as the original demo:

- `TEMPORAL_ADDRESS`
- `TEMPORAL_NAMESPACE`
- `TEMPORAL_API_KEY`, `TEMPORAL_TLS`, `TEMPORAL_TLS_CERT`, `TEMPORAL_TLS_KEY` for Temporal Cloud
- `LANGGRAPH_TEMPORAL_TASK_QUEUE` to override the default task queue
- `DB_URL`
- `BACKEND_URL` on deployed workers, pointing to the private backend service;
  leave unset for direct-database source runs
- `LLM_PROVIDER=anthropic` or `LLM_PROVIDER=openai`
- `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`
- `ANTHROPIC_MODEL`
- `OPENAI_MODEL`
- `OPENAI_FAILURE_RATE` to simulate retryable OpenAI planning failures
- `PORT` for the HTTP API container/listener
- `CORS_ALLOW_ORIGINS` as a comma-separated list for browser clients
- `DEMO_ACCESS_TOKEN` to require `X-Demo-Token` or `Authorization: Bearer`
  on conversation endpoints in public deployments
- `DEMO_AUTH_REQUIRED=true` to fail startup when the public-demo token is absent

Default task queue:

```text
support-agent-temporal-langgraph
```

## Public Demo Access Gate

Set `DEMO_ACCESS_TOKEN` and `DEMO_AUTH_REQUIRED=true` in deployed environments. The API will reject
conversation endpoints with `401` unless the request includes either:

```text
X-Demo-Token: <token>
Authorization: Bearer <token>
```

The web UI sends this token when opened with:

```text
?token=<token>
```

The UI immediately removes the token from the address bar and stores it only for
the active browser session. Leave both settings unset for local development only.

## Docker Images

Build the shared API/worker image from the repository root:

```bash
docker build -f docker/backend.Dockerfile -t langgraph-temporal-demo-backend .
```

Run the API:

```bash
docker run --rm -p 8002:8000 --env-file .env langgraph-temporal-demo-backend
```

Run the worker with the same image:

```bash
docker run --rm --env-file .env langgraph-temporal-demo-backend python worker.py
```

For production, set `TEMPORAL_ADDRESS`, `DB_URL`, and `BACKEND_URL` to routable
Cloud or ClusterIP endpoints. Do not use `localhost` in deployment config. The
public API is also available under `/api`, including `GET /api/health`.

## Docker Operations

The music catalog and customer data live in the Postgres container defined in
`../docker-compose.yml`. Run these commands from the repository root.

Start the database:

```bash
docker compose up -d postgres
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
docker compose up -d postgres
```

## Simulate OpenAI API Failures

`OPENAI_FAILURE_RATE` is checked inside the LangGraph `plan` node. Because that
node runs as a Temporal Activity, simulated failures are retryable Temporal
Activity failures.

Fail 20% of OpenAI planning calls:

```bash
LLM_PROVIDER=openai OPENAI_FAILURE_RATE=0.2 uv run python worker.py
```

Disable simulated failures:

```bash
OPENAI_FAILURE_RATE=0 uv run python worker.py
```

## Demo Cloud Registry

This folder is the app source for the Temporal + LangGraph demo. Demo cloud
onboarding should add a registry YAML under
`tmprl-demo-cloud-registry/projects/demo`; do not move this source into the
registry repository. Instruqt is not required for this deployment path.
