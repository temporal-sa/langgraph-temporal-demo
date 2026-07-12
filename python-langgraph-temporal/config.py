"""The one place that reads environment config. Everything else imports from here."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load repo-root .env (shared demoer quick-switch), then local overrides.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
load_dotenv()

TASK_QUEUE = os.getenv(
    "LANGGRAPH_TEMPORAL_TASK_QUEUE", "support-agent-temporal-langgraph"
)

# Temporal connection — local dev server by default; Temporal Cloud via env.
TEMPORAL_ADDRESS = os.getenv("TEMPORAL_ADDRESS", "localhost:7233")
TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE", "default")
TEMPORAL_API_KEY = os.getenv("TEMPORAL_API_KEY")
TEMPORAL_TLS_CERT = os.getenv("TEMPORAL_TLS_CERT")
TEMPORAL_TLS_KEY = os.getenv("TEMPORAL_TLS_KEY")

# Database — docker compose up -d (local) or an in-cluster Service (EKS).
DB_URL = os.getenv("DB_URL", "postgresql://demo:demo@localhost:5432/chinook")

# When set on the worker, tool activities call the private backend service
# instead of connecting to Postgres directly. Source-only local runs can leave
# this unset and keep the original direct-database behavior.
BACKEND_URL = os.getenv("BACKEND_URL", "").rstrip("/")


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _failure_rate(name: str) -> float:
    raw = os.getenv(name, "0")
    try:
        value = float(raw)
    except ValueError as e:
        raise ValueError(f"{name} must be a number between 0 and 1") from e
    if not 0 <= value <= 1:
        raise ValueError(f"{name} must be between 0 and 1")
    return value


# LLM provider, routed through LangChain chat-model integrations.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
OPENAI_FAILURE_RATE = _failure_rate("OPENAI_FAILURE_RATE")

# HTTP API settings.
PORT = int(os.getenv("PORT", "8002"))
CORS_ALLOW_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ALLOW_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:8080,http://127.0.0.1:8080",
    ).split(",")
    if origin.strip()
]

# Optional shared-token gate for public demo deployments. Leave unset for local
# development, or set DEMO_AUTH_DISABLED=true to bypass deliberately.
DEMO_ACCESS_TOKEN = os.getenv("DEMO_ACCESS_TOKEN")
DEMO_AUTH_DISABLED = _bool("DEMO_AUTH_DISABLED", default=False)
DEMO_AUTH_REQUIRED = _bool("DEMO_AUTH_REQUIRED", default=False)
if DEMO_AUTH_REQUIRED and not DEMO_ACCESS_TOKEN:
    raise RuntimeError("DEMO_ACCESS_TOKEN is required when DEMO_AUTH_REQUIRED=true")

TEMPORAL_TLS = _bool("TEMPORAL_TLS", default=False)


async def temporal_client():
    """Connect to Temporal — local dev server, Cloud (API key), or Cloud (mTLS)."""
    from temporalio.client import Client, TLSConfig
    from temporalio.contrib.pydantic import pydantic_data_converter

    common = {"namespace": TEMPORAL_NAMESPACE, "data_converter": pydantic_data_converter}

    if TEMPORAL_API_KEY:
        return await Client.connect(
            TEMPORAL_ADDRESS, api_key=TEMPORAL_API_KEY, tls=True, **common
        )
    if TEMPORAL_TLS_CERT and TEMPORAL_TLS_KEY:
        tls = TLSConfig(
            client_cert=Path(TEMPORAL_TLS_CERT).read_bytes(),
            client_private_key=Path(TEMPORAL_TLS_KEY).read_bytes(),
        )
        return await Client.connect(TEMPORAL_ADDRESS, tls=tls, **common)
    if TEMPORAL_TLS:
        return await Client.connect(TEMPORAL_ADDRESS, tls=True, **common)
    return await Client.connect(TEMPORAL_ADDRESS, **common)
