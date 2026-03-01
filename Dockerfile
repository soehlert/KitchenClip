FROM python:3.13-slim AS builder

RUN mkdir /app

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --upgrade pip && python3 -m pip install uv

# Copy UV files first (better caching)
COPY pyproject.toml uv.lock ./

RUN uv lock
RUN uv sync --no-install-project

FROM python:3.13-slim

RUN useradd -m -r appuser && \
    mkdir -p /app/data /app/media /app/staticfiles

RUN python3 -m pip install --upgrade pip && python3 -m pip install uv

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY . .
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]

# --- Test stage (not shipped to production) ---
FROM python:3.13-slim AS test

RUN useradd -m -r appuser && \
    mkdir -p /app/data /app/media /app/staticfiles

RUN python3 -m pip install --upgrade pip && python3 -m pip install uv

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY . .
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Install dev dependencies (pytest, playwright, etc.)
COPY pyproject.toml uv.lock ./
RUN uv sync --dev --no-install-project

# Install Playwright OS-level system dependencies (requires root/apt)
RUN playwright install-deps chromium

RUN chown -R appuser:appuser /app

USER appuser

# Install the chromium browser binary into /home/appuser/.cache (as appuser so it's accessible)
RUN playwright install chromium