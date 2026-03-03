"""Command-line interface for Nexus."""

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

import nexus
from nexus.core.config import settings

app = typer.Typer(
    name="nexus",
    help="Nexus -- Real-time prediction market intelligence engine",
    add_completion=False,
)
console = Console()


@app.command()
def info() -> None:
    """Display configuration and version info."""
    table = Table(title="Nexus Configuration")
    table.add_column("Setting", style="cyan", no_wrap=True)
    table.add_column("Value", style="green")

    table.add_row("Version", nexus.__version__)
    table.add_row("Debug", str(settings.debug))
    table.add_row("Log Level", settings.log_level)
    table.add_row("Kalshi URL", settings.effective_kalshi_url)
    table.add_row(
        "Kalshi API Key",
        (settings.kalshi_api_key[:8] + "...") if settings.kalshi_api_key else "(not set)",
    )
    table.add_row(
        "Kalshi Key Path",
        settings.kalshi_private_key_path or "(not set)",
    )
    table.add_row("Demo Mode", str(settings.kalshi_use_demo))
    table.add_row("SQLite Path", settings.sqlite_path)
    table.add_row("Discovery Interval", f"{settings.discovery_interval_seconds}s")
    table.add_row("Rate Limit", f"{settings.kalshi_reads_per_second} reads/sec")

    console.print(table)


@app.command(name="db-init")
def db_init() -> None:
    """Initialize the SQLite event store (create tables)."""
    from nexus.store.sqlite import SQLiteStore

    async def _init() -> None:
        store = SQLiteStore(settings.sqlite_path)
        await store.initialize()
        await store.close()

    asyncio.run(_init())
    console.print(f"Database initialized at [bold]{settings.sqlite_path}[/bold]")


@app.command(name="db-stats")
def db_stats() -> None:
    """Show event store statistics."""
    from nexus.store.sqlite import SQLiteStore

    async def _stats() -> tuple[int, int]:
        store = SQLiteStore(settings.sqlite_path)
        await store.initialize()
        mc = await store.get_market_count()
        ec = await store.get_event_count()
        await store.close()
        return mc, ec

    market_count, event_count = asyncio.run(_stats())

    table = Table(title="Event Store Statistics")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Markets", str(market_count))
    table.add_row("Events", str(event_count))
    table.add_row("Database", settings.sqlite_path)
    console.print(table)


@app.command()
def discover() -> None:
    """Run a single discovery cycle (one-shot, no loop)."""
    from nexus.adapters.kalshi import KalshiAdapter
    from nexus.ingestion.discovery import DiscoveryLoop
    from nexus.store.sqlite import SQLiteStore

    async def _discover() -> None:
        store = SQLiteStore(settings.sqlite_path)
        await store.initialize()

        async with KalshiAdapter(settings) as adapter:
            loop = DiscoveryLoop(
                adapters=[adapter],
                store=store,
                interval_seconds=0,
            )
            results = await loop.run_once()

        mc = await store.get_market_count()
        ec = await store.get_event_count()
        await store.close()

        console.print(f"Discovery results: {results}")
        console.print(f"Store: {mc} markets, {ec} events")

    asyncio.run(_discover())


@app.command()
def run() -> None:
    """Start the discovery polling loop (ctrl-c to stop)."""
    from nexus.adapters.kalshi import KalshiAdapter
    from nexus.ingestion.discovery import DiscoveryLoop
    from nexus.store.sqlite import SQLiteStore

    async def _run() -> None:
        store = SQLiteStore(settings.sqlite_path)
        await store.initialize()

        async with KalshiAdapter(settings) as adapter:
            loop = DiscoveryLoop(
                adapters=[adapter],
                store=store,
                interval_seconds=settings.discovery_interval_seconds,
            )
            console.print(
                f"Polling every {settings.discovery_interval_seconds}s "
                f"(ctrl-c to stop)"
            )
            try:
                await loop.run_forever()
            except asyncio.CancelledError:
                pass
            finally:
                await loop.stop()

        await store.close()
        console.print("Stopped.")

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        console.print("\nShutdown requested.")


if __name__ == "__main__":
    app()
