# Multi-stage: dependencies are compiled into wheels in the builder, then only
# the wheels are installed in the runtime image. Build toolchains (gcc, headers)
# never reach the final image, which cuts both size and attack surface.
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# The shared events package is a local path dependency, so it has to be present
# before requirements are resolved.
COPY shared/ ./shared/
COPY services/claims-api/requirements.txt ./requirements.txt

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install -r requirements.txt


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /build/shared /shared

WORKDIR /app
COPY services/claims-api/app ./app
COPY services/claims-api/alembic ./alembic
COPY services/claims-api/alembic.ini ./alembic.ini
COPY services/claims-api/scripts ./scripts

RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Readiness is what Kubernetes probes; this HEALTHCHECK is for docker-compose
# and local runs, where nothing else is watching.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health/ready || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
