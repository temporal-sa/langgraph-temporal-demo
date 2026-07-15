FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY support-agent-common /support-agent-common
COPY python-langgraph/pyproject.toml python-langgraph/uv.lock ./
RUN uv sync --frozen --no-dev

COPY python-langgraph/ ./

EXPOSE 8001
CMD ["python", "-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8001"]
