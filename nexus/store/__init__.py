"""Event store abstraction layer."""

from nexus.store.base import BaseStore


def create_store(settings: object) -> BaseStore:
    """Create the appropriate store backend based on settings.

    Args:
        settings: A Settings instance with store_backend, sqlite_path,
                  postgres_dsn, postgres_pool_min, postgres_pool_max.

    Returns:
        An uninitialized BaseStore. Caller must await store.initialize().
    """
    backend = getattr(settings, "store_backend", "sqlite")

    if backend == "postgres":
        from nexus.store.postgres import PostgresStore

        dsn = getattr(settings, "postgres_dsn", "")
        if not dsn:
            raise ValueError(
                "store_backend is 'postgres' but POSTGRES_DSN is not set"
            )
        return PostgresStore(
            dsn=dsn,
            pool_min=getattr(settings, "postgres_pool_min", 2),
            pool_max=getattr(settings, "postgres_pool_max", 10),
        )

    # Default: SQLite
    from nexus.store.sqlite import SQLiteStore

    return SQLiteStore(getattr(settings, "sqlite_path", "data/nexus.db"))
