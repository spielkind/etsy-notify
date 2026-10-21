# syntax=docker/dockerfile:1

FROM python:3.15-slim-trixie@sha256:f5b92f2a669a4c347044f29367f31983280b648250ca94dea66f98c53bc87e58 AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13@sha256:9f130421e930bfbdc563c00740466603f8723158e90297d07957c2294640262b /uv /bin/uv

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


FROM python:3.15-slim-trixie@sha256:f5b92f2a669a4c347044f29367f31983280b648250ca94dea66f98c53bc87e58

# Time zone data, so that TZ (e.g. Europe/Berlin) applies to notifications and logs.
# pip is not needed at runtime (the app runs from its own venv) and only brings
# outdated vendored copies of certifi, urllib3 etc. into the image.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip uninstall --yes --quiet pip \
    && rm -f /usr/local/bin/pip*

RUN groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid 1000 --home-dir /data --shell /usr/sbin/nologin app \
    && mkdir /data && chown 1000:1000 /data

COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/data/shop-notify.db \
    LOG_FILE=""

USER 1000:1000
WORKDIR /data
VOLUME /data

HEALTHCHECK --interval=60s --timeout=10s --start-period=120s --retries=3 \
    CMD ["shop-notify", "healthcheck"]

ENTRYPOINT ["shop-notify"]
