# =============================================================================
# StockPilot - production image for the FastAPI API, built from the repository
# root:
#
#     docker build -t stockpilot-api:local .
#     docker run --rm -p 8000:8000 --env-file .env stockpilot-api:local
#
# Why a second API Dockerfile next to `backend/Dockerfile`?
#   * `backend/Dockerfile` is the compose-oriented image (context = `backend/`)
#     used by docker-compose.dev.yml / docker-compose.prod.yml.
#   * this root image installs from the *committed lockfile*
#     (`backend/requirements.lock`), so the bits are reproducible from the
#     repository alone, and it is the image the tag-triggered release job in
#     .github/workflows/ci.yml builds and publishes to GHCR.
#
# Both images are built on every push (`docker` job in ci.yml), so a change to
# either file fails the build instead of drifting silently.
# =============================================================================
FROM python:3.14-slim AS builder

WORKDIR /build

# Toolchain for wheels without a prebuilt binary (psycopg2, reportlab).
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt backend/requirements.lock ./

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.lock

# ---------------------------------------------------------------------------
# Runtime stage
# ---------------------------------------------------------------------------
FROM python:3.14-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system appuser \
    && useradd --system --gid appuser --home-dir /app appuser

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=appuser:appuser backend/ /app/

RUN chmod +x /app/entrypoint.sh \
    && mkdir -p /app/uploads \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
