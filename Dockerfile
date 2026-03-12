FROM python:3.11-slim AS builder

WORKDIR /app

# Install build deps for cryptography (RSA auth) and asyncpg
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Install poetry
RUN pip install --no-cache-dir poetry==1.8.5

# Copy dependency files and application code (needed for poetry install to create entry point)
COPY pyproject.toml poetry.lock ./
COPY nexus/ nexus/
COPY sql/ sql/

# Install runtime deps + project entry point (no dev, with postgres extra)
RUN poetry config virtualenvs.create false && \
    poetry install --no-interaction --no-ansi --without dev -E postgres

FROM python:3.11-slim AS production

WORKDIR /app

# Only runtime lib needed (not gcc/dev headers)
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq5 && \
    rm -rf /var/lib/apt/lists/*

# Copy installed packages and CLI entry point from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin/ /usr/local/bin/

# Copy application code
COPY nexus/ nexus/
COPY sql/ sql/

# Non-root user for security
RUN useradd --create-home nexus
USER nexus

CMD ["python", "-m", "nexus.cli", "run"]
