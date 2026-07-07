# Support Agent with LangGraph

This folder is a standalone LangGraph version of the music-store support agent.
LangGraph runs the ReAct loop in process, and the API keeps demo conversation
state in memory.

## Run

From this folder:

```bash
cd ..
docker compose up -d
cd python-langchain
uv run starter.py
```

For the HTTP API:

```bash
cd ..
docker compose up -d
cd python-langchain
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

Conversations are process-local. Restarting the API clears them.

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
