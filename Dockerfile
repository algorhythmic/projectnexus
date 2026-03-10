FROM python:3.11-slim AS base

WORKDIR /app

# Install system deps for cryptography (RSA auth) and asyncpg
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Install poetry
RUN pip install --no-cache-dir poetry==1.8.5

# Copy dependency files first for layer caching
COPY pyproject.toml poetry.lock ./

# Install runtime deps (no dev, with postgres extra)
RUN poetry config virtualenvs.create false && \
    poetry install --no-interaction --no-ansi --without dev -E postgres

# Copy application code
COPY nexus/ nexus/
COPY sql/ sql/

# Verify CLI works
RUN nexus info || true

FROM base AS production

# Non-root user for security
RUN useradd --create-home nexus
USER nexus

ENTRYPOINT ["nexus"]
CMD ["run"]
