# Web UI — chat frontend for the support agent

A single-page vanilla-JS chat (no framework, no build step) that drives whichever gateway
implements the shared `/conversations` HTTP endpoints.

## Point it at a backend

The start screen includes a backend selector. Presets live in `config.js`:

| Backend | Preset ID | Default URL |
| --- | --- | --- |
| Original Temporal workflow | `temporal` | `http://localhost:8000` |
| Temporal + LangGraph workflow | `temporal-langgraph` | `http://localhost:8002` |
| Standalone LangGraph app | `langgraph` | `http://localhost:8001` |

Use a query string to force a backend without changing files:

```text
http://localhost:5173?backend=temporal
http://localhost:5173?backend=temporal-langgraph
http://localhost:5173?backend=langgraph
```

To change ports or labels, edit the matching entry in `config.js`.

## Run it

Use separate terminals for the database, backend processes, and web UI. The
commands below assume you start in this `web/` folder.

Database terminal:

```bash
cd ..
docker compose up -d
```

Start the backend you want to test.

Standalone LangGraph app:

```bash
cd ../python-langchain
uv run uvicorn api:app --port 8001
```

Original Temporal workflow gateway:

```bash
cd ../python
uv run uvicorn api:app --port 8000
```

For the original Temporal workflow gateway, also run the Temporal server and worker
from separate terminals:

```bash
cd ..
temporal server start-dev --ui-port 8233
```

```bash
cd ../python
uv run worker.py
```

Temporal + LangGraph workflow gateway:

```bash
cd ../python-langchain-temporal
uv run uvicorn api:app --port 8002
```

For the Temporal + LangGraph gateway, also run the Temporal server and its
LangGraph worker from separate terminals:

```bash
cd ..
temporal server start-dev --ui-port 8233
```

```bash
cd ../python-langchain-temporal
uv run worker.py
```

The `temporal-langgraph` preset expects this gateway to listen on
`http://localhost:8002`. If you run it on another port, update `config.js`.

Web UI terminal:

```bash
python3 -m http.server 5173
# open http://localhost:5173
```

## Shut it down

In the terminals running the web UI, backend, Temporal server, or worker, press
`Ctrl-C`.

Then stop the database from any terminal:

```bash
cd ..
docker compose stop postgres
```

To stop and remove the database container:

```bash
cd ..
docker compose down
```

To reset the database completely, including seeded data:

```bash
cd ..
docker compose down -v
```

## Troubleshooting

If `http://localhost:5173` shows the wrong app or does not load this UI, check
what is using the port:

```bash
lsof -nP -iTCP:5173 -sTCP:LISTEN
```

Stop the conflicting process, or run this UI on another port:

```bash
python3 -m http.server 5174
```

If you use another web port, backend selection still works the same way with the
start-screen selector or `?backend=...` query string.

## Develop against the stub (no Temporal, no LLM, no DB)

`stub-server.mjs` is a dependency-free Node server that implements the API contract with
canned behavior — it exists so the UI can be built/tested alone, and it doubles as the
reference the SDK gateways are built against in Phase 1.

```bash
node stub-server.mjs        # listens on :8000
```

- Any message → echo reply after a short "thinking" delay.
- A message containing **"buy"** or **"purchase"** → the `awaiting_approval` flow
  (approval card with Approve/Reject; the outcome lands via transcript polling).

## What to notice (for demo purposes)

- The header shows the conversation ID returned by the backend.
- The approval card is the HITL beat: while it's showing, the agent is waiting for
  approve/reject before it runs the purchase tool.
