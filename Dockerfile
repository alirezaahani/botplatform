FROM python:3.12-slim AS base
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
RUN pip install --no-cache-dir uv==0.13.1 \
    && useradd --create-home app
WORKDIR /app

# Chrome for Testing and its matching chromedriver, pinned to one exact version (amd64 only).
# This stage depends only on the version, so other changes never download Chrome again.
FROM base AS chrome
ARG CHROME_VERSION=156.0.8078.80
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl unzip \
    && base="https://storage.googleapis.com/chrome-for-testing-public/${CHROME_VERSION}/linux64" \
    && for name in chrome chromedriver; do \
        curl -fsSL -o "/tmp/${name}.zip" "${base}/${name}-linux64.zip" \
        && unzip -q "/tmp/${name}.zip" -d /opt && rm "/tmp/${name}.zip"; \
    done

FROM base AS web
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra web --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra web --no-editable
COPY alembic.ini ./
COPY migrations ./migrations
USER app
CMD ["uvicorn", "botplatform.web.app:app", "--host", "0.0.0.0", "--port", "8000"]

# System packages and the pinned Chrome, shared by the worker and test images.
FROM base AS browser
ENV CHROME_BINARY=/opt/chrome-linux64/chrome \
    CHROMEDRIVER_BINARY=/opt/chromedriver-linux64/chromedriver
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates fonts-liberation \
        libasound2t64 libatk-bridge2.0-0 libatk1.0-0 libcairo2 libcups2 libdbus-1-3 libdrm2 \
        libgbm1 libglib2.0-0 libnspr4 libnss3 libpango-1.0-0 libx11-6 libxcb1 libxcomposite1 \
        libxdamage1 libxext6 libxfixes3 libxkbcommon0 libxrandr2 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=chrome /opt/chrome-linux64 /opt/chrome-linux64
COPY --from=chrome /opt/chromedriver-linux64 /opt/chromedriver-linux64

FROM browser AS worker
# The virtual display and the viewer (see worker/start.sh). The web image never gets these.
RUN apt-get update \
    && apt-get install -y --no-install-recommends xvfb x11vnc novnc websockify \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra worker --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra worker --no-editable
COPY --chmod=755 worker/start.sh /usr/local/bin/start-worker
USER app
CMD ["start-worker"]

# Tests: the worker's browser plus pytest (dev group) and FastAPI for the fake demo page.
FROM browser AS test
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra worker --extra web --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra worker --extra web --no-editable
COPY tests ./tests
USER app
CMD ["pytest"]
