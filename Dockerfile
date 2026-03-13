# Use a specific digest for immutability and slim for small size
FROM python:3.11-slim AS builder

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
FROM python:3.11-slim

WORKDIR /app

# Copy the virtualenv from builder and the app code
COPY --from=builder /venv /venv
COPY . .

ENV PYTHONUNBUFFERED=1

# Use a non-root user for security (OWASP Best Practice)
# Note: Ensure your session file has write permissions for this user
RUN useradd -m botuser && chown -R botuser /app
USER botuser

# The -u flag is critical for cloud logging
CMD ["/venv/bin/python", "-u", "main.py"]