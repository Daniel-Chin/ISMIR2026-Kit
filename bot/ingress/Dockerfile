# Build from the bot/ directory:  docker build -f ingress/Dockerfile .
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY shared/ shared/
COPY ingress/ ingress/

ENV PATH="/app/.venv/bin:$PATH"
CMD exec gunicorn --bind :$PORT --workers 2 --threads 8 --timeout 30 ingress.app:flask_app
