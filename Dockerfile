# Multi-stage, so build tooling never ships.
#
#   builder  — resolves the locked dependencies and installs the project
#   dev      — builder plus the dev dependencies, tests, and migrations
#   runtime  — slim, non-root, no uv, no pytest/ruff/mypy

FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Dependencies before source, so a code change does not invalidate this layer.
# --frozen fails the build on a stale lock rather than quietly resolving
# something different from the local environment.
# LICENSE travels with pyproject.toml: `license-files` declares it, so the
# project install below fails without it — and BSD-3 requires the notice to
# accompany the redistributed binary in any case.
COPY pyproject.toml uv.lock LICENSE ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ ./src/
RUN uv sync --frozen --no-dev


FROM builder AS dev

# The same base and the same lock as the image above; dev dependencies and the
# things only a developer runs.
RUN uv sync --frozen
COPY alembic.ini ./
COPY alembic/ ./alembic/
COPY tests/ ./tests/

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]


FROM python:3.13-slim AS runtime

# A container running as root is a privilege escalation waiting for a container
# escape.
RUN useradd --create-home --uid 1000 app

WORKDIR /app
COPY --from=builder --chown=app:app /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER app
EXPOSE 8000

# Logs go to stdout; the platform collects them.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
