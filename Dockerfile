FROM python:3.13-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Copy project files first
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-dev

# Copy application code
COPY . .

# Collect static files (now with WhiteNoise)
RUN uv run python manage.py collectstatic --noinput

EXPOSE 8000

# Fixed module name: KitchenClip not kitchenclip
CMD ["uv", "run", "gunicorn", "KitchenClip.wsgi:application", "--bind", "0.0.0.0:8000"]
