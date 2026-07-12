# LangGraph Temporal Demo

Music-store support-agent demo showing durable agent execution, tool use, and
human approval. The repository keeps three implementations for local
comparison:

- `python/` — original Temporal workflow.
- `python-langgraph/` — standalone LangGraph.
- `python-langgraph-temporal/` — Temporal-backed LangGraph, used by the
  containerized production deployment.

## Deployment architecture

The production stack follows the Déjà Vu Tacos operational model. The backend
and worker reuse one Python app image but run as independent processes.

```text
Browser
  |
  | https://langgraph-temporal.tmprl-demo.cloud
  v
tmprl-demo.cloud ingress
  |-- /* -----> frontend (nginx/static UI)
  `-- /api/* -> backend (FastAPI) ------> Temporal Cloud
                    ^                         ^
                    | private ClusterIP       | task queue
                    |                         |
              worker activities <------ Temporal worker
                    |
                    `-- tool calls through backend -> Postgres
```

Kubernetes never runs a Temporal Server. The backend starts, signals, updates,
and queries workflows in Temporal Cloud. The independently restartable worker
polls the same Cloud task queue and calls the operator-created backend service
through `BACKEND_URL=http://backend:8000`.

## Local quick start

For the source-based comparison environment:

```bash
cp .env.example .env
# Add ANTHROPIC_API_KEY or OPENAI_API_KEY to .env
make up
```

Open `http://localhost:5173`. The selector exposes all three implementations.
The Temporal UI is at `http://localhost:8233`. Stop everything with `make down`.

## Docker Compose

Compose runs the production-shaped frontend, backend, worker, and Postgres
containers while using a Temporal dev server on the host:

```bash
cp .env.example .env
temporal server start-dev --ui-port 8233
make compose-up
```

Open `http://localhost:5173`. Compose maps the backend to
`http://localhost:8002`, but the browser uses same-origin `/api` through nginx.
The containers reach the host Temporal server at
`host.docker.internal:7233`. Stop the stack with `make compose-down`.

You can also use `docker compose up --build -d` directly.
If a source-based process already owns a default port, override it with
`COMPOSE_WEB_PORT`, `COMPOSE_API_PORT`, or `COMPOSE_POSTGRES_PORT`.

## Runtime configuration

Local defaults live in `.env.example`. Production configuration is declared in
the `DemoProject` resource in `tmprl-demo-cloud-registry`. The platform injects
Temporal Cloud values, while project-owned credentials are read from AWS
Secrets Manager. The local `.env` is never uploaded by the deployment.

| Variable | Purpose |
| --- | --- |
| `TEMPORAL_ADDRESS` | Temporal frontend endpoint, including port |
| `TEMPORAL_NAMESPACE` | Temporal Cloud namespace ID |
| `TEMPORAL_API_KEY` | Namespace-scoped Cloud API key; secret |
| `TEMPORAL_TLS` | `true` in production |
| `LANGGRAPH_TEMPORAL_TASK_QUEUE` | Shared backend/worker task queue |
| `BACKEND_URL` | Private worker-to-backend base URL |
| `DB_URL` | PostgreSQL connection URL; secret |
| `LLM_PROVIDER` | `anthropic` or `openai` |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | Selected provider credential; secret |
| `ANTHROPIC_MODEL` / `OPENAI_MODEL` | Selected provider model ID |
| `DEMO_ACCESS_TOKEN` | Shared public-demo application token; secret |
| `CORS_ALLOW_ORIGINS` | Comma-separated browser origins |

For OpenAI Sol, for example:

```env
LLM_PROVIDER=openai
OPENAI_MODEL=gpt-5.6-sol
OPENAI_API_KEY=...
```

No credentials are copied into images or committed manifests.

## Container images

Build for the Kubernetes target platform:

```bash
docker buildx build --platform linux/amd64 --load \
  -f docker/backend.Dockerfile -t langgraph-temporal-demo-app:local .
docker buildx build --platform linux/amd64 --load \
  -f docker/frontend.Dockerfile -t langgraph-temporal-demo-frontend:local .
docker buildx build --platform linux/amd64 --load \
  -f docker/postgres.Dockerfile -t langgraph-temporal-demo-postgres:local .
```

The app image runs FastAPI by default. The worker deployment reuses it with
`python worker.py`.

## tmprl-demo.cloud deployment

This repository owns application source and Dockerfiles only. Deployment is
defined by one `DemoProject` resource in the private
`tmprl-demo-cloud-registry` repository:

```text
projects/demo/langgraph-temporal.yaml
```

After that resource is merged, the registry operator builds the three images,
runs frontend, backend, worker, and seeded Postgres as separate components,
creates the Temporal Cloud namespace and credentials, and publishes:

```text
https://langgraph-temporal.tmprl-demo.cloud
```

Before onboarding, the source repository must be available at
`https://github.com/temporal-sa/langgraph-temporal-demo`. Create these JSON
secrets in AWS Secrets Manager in the platform account and `us-west-1`:

| Secret path | Required properties |
| --- | --- |
| `tmprl-dem-cld/langgraph-temporal/llm-credentials` | `OPENAI_API_KEY` |
| `tmprl-dem-cld/langgraph-temporal/database` | `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DB_URL` |
| `tmprl-dem-cld/langgraph-temporal/demo-access` | `DEMO_ACCESS_TOKEN` |

Temporal credentials are platform-owned and must not be added to these
secrets. See [`DEPLOYMENT.md`](DEPLOYMENT.md) for the onboarding sequence.

## Validation

```bash
make test
docker compose config --quiet

# From the tmprl-demo-cloud-registry checkout after adding the DemoProject:
uv run --isolated --with jsonschema --with pyyaml \
  python scripts/validate_projects.py
```
