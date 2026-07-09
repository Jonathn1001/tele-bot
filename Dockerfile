# Digest-pinned for immutability; 3.12 matches local dev and CI.
# Refresh digest deliberately: docker buildx imagetools inspect python:3.12-slim
FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf AS builder

# Set environment variables to optimize Python for containers
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install build dependencies only if your requirements need to compile C extensions
# (Common for some crypto libs used by Telethon)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install into a virtualenv so the final stage can copy a single known path
RUN python -m venv /venv && \
    /venv/bin/pip install --upgrade pip && \
    /venv/bin/pip install --no-cache-dir -r requirements.txt

# Final Stage
FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf

WORKDIR /app

# Copy the virtualenv from builder and only the app source.
# Explicit COPY (plus .dockerignore) keeps secrets like .env, session files
# and SSH keys out of image layers.
COPY --from=builder /venv /venv
COPY *.py ./

ENV PYTHONUNBUFFERED=1

# Use a non-root user for security (OWASP Best Practice)
# Note: Ensure your session file has write permissions for this user
RUN useradd -m botuser && chown -R botuser /app
USER botuser

# Report unhealthy in `docker ps` when the heartbeat goes stale; the in-process
# watchdog (health.py) does the actual restart. start-period covers backfill.
HEALTHCHECK --interval=60s --timeout=10s --start-period=180s --retries=3 \
    CMD ["/venv/bin/python", "-c", "import health,sys; sys.exit(0 if health.is_fresh() else 1)"]

# The -u flag is critical for cloud logging
CMD ["/venv/bin/python", "-u", "main.py"]