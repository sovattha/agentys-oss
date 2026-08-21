# Agentys Dockerfile
# Pipeline Multi-Agents IA pour Email
#
# Build:
#   docker build -t agentys .
#
# Run:
#   docker run -d --name agentys -v $(pwd)/.env:/app/.env agentys
#
# Setup:
#   docker run -it --rm -v $(pwd)/.env:/app/.env agentys setup
#

FROM python:3.12-slim

# Metadata
LABEL maintainer="Agentys Team"
LABEL description="Pipeline Multi-Agents IA pour génération de réponses email"
LABEL version="1.0"

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Working directory
WORKDIR /app

# Install system dependencies
# gosu: drop from root to the non-root 'agentys' user at runtime AFTER chowning
# the (root-owned) Railway volume — see docker/entrypoint.sh (audit 2026-05-29, CWE-250).
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN groupadd --gid 1000 agentys \
    && useradd --uid 1000 --gid agentys --shell /bin/bash --create-home agentys

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Cache-bust: update this value to force Railway to rebuild the app/ COPY layer
# when Docker's content-hash cache misses an updated file (happened 2026-04-14
# with routes_learning.py /writing-style/* sub-routes).
ARG CACHEBUST=2026-04-14T15-00Z-writing-style
RUN echo "Cache bust: ${CACHEBUST}"

# Copy application code
COPY app/ app/
COPY knowledge/ knowledge/
COPY alembic.ini .
COPY scripts/migrate_sqlite_to_postgres.py scripts/migrate_sqlite_to_postgres.py
COPY scripts/audit_email_content_retention.py scripts/audit_email_content_retention.py
COPY scripts/backfill_recap_quality_account_ids.py scripts/backfill_recap_quality_account_ids.py
COPY scripts/railway_entrypoint.py scripts/railway_entrypoint.py
COPY run_daemon.py .
COPY run_api.py .
COPY setup.py .
COPY .env.example .
COPY docker/entrypoint.sh /entrypoint.sh

# Create data directories and set permissions
RUN mkdir -p data logs agents \
    && chmod +x /entrypoint.sh \
    && chown -R agentys:agentys /app /entrypoint.sh

# Note: USER agentys retiré pour permettre l'écriture sur les volumes Railway
# montés en root. Container isolé en prod, root acceptable.
# Pour réintroduire un user non-root, prévoir un init qui chown le volume
# avant de drop les privilèges (via gosu/su-exec installé séparément).

# Health check — use /api/health when running as API, fallback to import check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT:-5050}/api/health || python -c "import app.config; print('healthy')" || exit 1

# Entrypoint script handles setup and daemon modes
ENTRYPOINT ["/entrypoint.sh"]

# Default command: run API server
CMD ["api"]

# Expose default API port (Railway overrides via $PORT)
EXPOSE 5050
