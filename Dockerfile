FROM python:3.12-slim AS base
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
RUN pip install --no-cache-dir uv==0.13.1 \
    && useradd --create-home app
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src

FROM base AS web
RUN uv sync --frozen --no-dev --extra web --no-editable
COPY alembic.ini ./
COPY migrations ./migrations
USER app
CMD ["uvicorn", "botplatform.web.app:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS worker
RUN uv sync --frozen --no-dev --extra worker --no-editable
USER app
CMD ["python", "-m", "botplatform.worker.main"]
