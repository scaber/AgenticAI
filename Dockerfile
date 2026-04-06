# ---- Build stage ----
FROM python:3.12-slim AS builder

WORKDIR /build

# OS-level deps needed for compilation (gitpython, crypto libs)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc git && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ---- Runtime stage ----
FROM python:3.12-slim

LABEL maintainer="AI PR Agent Team"
LABEL description="AI-Powered Azure DevOps Agent: Autonomous PR Engine"

# git is needed at runtime for GitPython
RUN apt-get update && \
    apt-get install -y --no-install-recommends git curl && \
    rm -rf /var/lib/apt/lists/*

# Non-root user for security
RUN groupadd -r agent && useradd -r -g agent -m -s /bin/bash agent

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

WORKDIR /app

# Copy application code
COPY agents/ agents/
COPY config/ config/
COPY context/ context/
COPY models/ models/
COPY orchestrator/ orchestrator/
COPY services/ services/
COPY webhooks/ webhooks/
COPY main.py .
COPY pyproject.toml .
COPY docker-entrypoint.sh /usr/local/bin/

# Make entrypoint executable
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Create workspace directory for target repo clones
RUN mkdir -p /workspace && chown agent:agent /workspace
# Create index store directory
RUN mkdir -p /app/.index_store && chown agent:agent /app/.index_store

# Switch to non-root user
USER agent

# Default env vars (overridable)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    LOG_LEVEL=INFO \
    GIT_REPO_PATH=/workspace/target-repo

EXPOSE ${PORT}

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT}/webhooks/health || exit 1

ENTRYPOINT ["docker-entrypoint.sh"]

# Production server — uvicorn with multiple workers
CMD ["python", "-m", "uvicorn", "main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--access-log", \
     "--log-level", "info"]
