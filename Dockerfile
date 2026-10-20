# syntax=docker/dockerfile:1

FROM python:3.15-slim-trixie AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-editable

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable


FROM python:3.15-slim-trixie

RUN useradd --system --uid 1000 --home-dir /data --shell /usr/sbin/nologin app \
    && mkdir /data && chown app:app /data

COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/data/shop-notify.db \
    LOG_FILE=""

USER app
WORKDIR /data
VOLUME /data

HEALTHCHECK --interval=60s --timeout=10s --start-period=120s --retries=3 \
    CMD ["shop-notify", "healthcheck"]

ENTRYPOINT ["shop-notify"]
