# Nexus

Real-time prediction market intelligence engine.

Nexus ingests streaming data from prediction market platforms (Kalshi, Polymarket), detects anomalous price and volume movements, identifies correlated shifts across semantically related markets, and surfaces structured alerts for human decision-making.

## Project Status

**Phase 1 — Foundation (Milestone 1.1: Project Scaffolding)**

- Kalshi REST adapter with RSA-PSS authentication
- SQLite event store (markets + events tables)
- Market discovery polling loop
- CLI for one-shot discovery and continuous polling

## Prerequisites

- Python 3.11+
- [Poetry](https://python-poetry.org/)

## Setup

```bash
# Install dependencies
poetry install

# Copy and configure environment variables
cp .env.example .env
# Edit .env with your Kalshi API key and private key path

# Initialize the database
poetry run nexus db-init
```

## Usage

```bash
# Show configuration
poetry run nexus info

# Run a single discovery cycle
poetry run nexus discover

# Start continuous polling (ctrl-c to stop)
poetry run nexus run

# Check database statistics
poetry run nexus db-stats
```

## Testing

```bash
poetry run pytest tests/ -v
```

## Project Structure

```
nexus/                  Python package
  core/                 Configuration, logging, shared types
  adapters/             Platform adapters (Kalshi, Polymarket)
  ingestion/            Discovery polling, event bus
  store/                Database abstraction (SQLite, PostgreSQL)
  correlation/          Anomaly detection (Phase 2)
  sync/                 Convex sync layer (Phase 3)
  cli.py                Command-line interface
sql/                    Schema DDL and migrations
tests/                  Test suite
```

## Architecture

See `projectnexus_specdoc.md` for the full specification.
