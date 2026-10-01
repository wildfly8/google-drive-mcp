# uv binary, pinned by version and digest (Dependabot bumps both).
FROM ghcr.io/astral-sh/uv:0.12.21@sha256:a7aed3216253ee804de3e2d8afa5073baa1a177335345d43845cd4165e43b711 AS uv

# Builder: install exactly what uv.lock pins (hashes checked) into /app/.venv.
FROM python:3.14-slim AS builder

COPY --from=uv /uv /bin/uv

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

COPY pyproject.toml uv.lock ./

# Dependencies only. The app runs from /app/src, so no build backend is fetched.
RUN uv sync --frozen --no-dev --no-install-project

# Runtime: the venv and the source, run as a non-root user.
FROM python:3.14-slim

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PORT=8080 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/src

COPY --from=builder /app/.venv /app/.venv
COPY src ./src

USER 10001

EXPOSE 8080

CMD ["python", "-m", "google_drive_mcp"]
