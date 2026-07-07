"""The one place that reads environment config. Everything else imports from here."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load repo-root .env (shared demoer quick-switch), then local overrides.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
load_dotenv()

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
