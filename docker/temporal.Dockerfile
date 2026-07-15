FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

RUN pip install --no-cache-dir uv

# Dependency metadata changes less often than source, preserving Docker cache.
COPY support-agent-common /support-agent-common
COPY python/pyproject.toml python/uv.lock ./
RUN uv sync --frozen --no-dev

COPY python/ ./

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
