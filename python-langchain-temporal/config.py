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
    return await Client.connect(TEMPORAL_ADDRESS, **common)
