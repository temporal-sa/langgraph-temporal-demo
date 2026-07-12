FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}" \
    PORT=8000

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

COPY support-agent-common /support-agent-common
COPY python-langgraph-temporal/pyproject.toml python-langgraph-temporal/uv.lock ./
RUN uv sync --frozen --no-dev

COPY python-langgraph-temporal/ ./

EXPOSE 8000

CMD ["sh", "-c", "python -m uvicorn api:app --host 0.0.0.0 --port ${PORT}"]
