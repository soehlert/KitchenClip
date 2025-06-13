FROM python:3.13-slim AS builder

RUN mkdir /app

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip && pip install uv

# Copy UV files first (better caching)
COPY pyproject.toml uv.lock ./

RUN uv sync --frozen

FROM python:3.13-slim

RUN useradd -m -r appuser && \
    mkdir -p /app/data /app/media /app/staticfiles

RUN pip install --upgrade pip && pip install uv

COPY --from=builder /app/.venv /app/.venv

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:$PATH"

COPY . .
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
RUN mkdir -p /app/data

RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]