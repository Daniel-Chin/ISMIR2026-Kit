# Build from the bot/ directory:  docker build -f worker/Dockerfile .
# The build copies catalogue/schema.py from the repo root at image-build time
# (single schema definition, LLM_plan.md section 2) — build with the repo
# root as context in CI, or run infra/vendor_schema.sh first locally.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY shared/ shared/
COPY worker/ worker/

ENV PATH="/app/.venv/bin:$PATH"
CMD exec gunicorn --bind :$PORT --workers 1 --threads 4 --timeout 300 worker.app:flask_app
