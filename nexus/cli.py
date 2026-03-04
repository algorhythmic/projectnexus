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
    """Start real-time ingestion (REST discovery + WebSocket streaming)."""
    from nexus.adapters.kalshi import KalshiAdapter
    from nexus.ingestion.bus import EventBus
    from nexus.ingestion.manager import IngestionManager
    from nexus.store.sqlite import SQLiteStore

    async def _run() -> None:
        store = SQLiteStore(settings.sqlite_path)
        await store.initialize()

        bus = EventBus(
            store=store,
            max_size=settings.event_queue_max_size,
            batch_size=settings.event_batch_size,
            batch_timeout=settings.event_batch_timeout,
        )
        bus.start()

        async with KalshiAdapter(settings) as adapter:
            manager = IngestionManager(adapter, store, bus, settings)
            console.print(
                f"Starting ingestion (discovery every "
                f"{settings.discovery_interval_seconds}s + WebSocket streaming). "
                f"Ctrl-c to stop."
            )
            try:
                await manager.run()
            except asyncio.CancelledError:
                pass
            finally:
                await manager.stop()

        await bus.stop()
        console.print(f"Events written: {bus.events_written}")
        await store.close()
        console.print("Stopped.")

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        console.print("\nShutdown requested.")


@app.command()
def poll() -> None:
    """Start discovery-only polling loop (no WebSocket)."""
    from nexus.adapters.kalshi import KalshiAdapter
    from nexus.ingestion.discovery import DiscoveryLoop
    from nexus.store.sqlite import SQLiteStore

    async def _poll() -> None:
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
        asyncio.run(_poll())
    except KeyboardInterrupt:
        console.print("\nShutdown requested.")


@app.command()
def stream() -> None:
    """Stream WebSocket events to console (debug tool, no storage)."""
    from nexus.adapters.kalshi import KalshiAdapter
    from nexus.store.sqlite import SQLiteStore

    async def _stream() -> None:
        # Load tickers from the store (requires prior discovery)
        store = SQLiteStore(settings.sqlite_path)
        await store.initialize()
        markets = await store.get_active_markets(platform="kalshi")
        tickers = [m.external_id for m in markets]
        await store.close()

        if not tickers:
            console.print(
                "[bold red]No markets found.[/bold red] "
                "Run [cyan]nexus discover[/cyan] first."
            )
            return

        console.print(
            f"Streaming {len(tickers)} tickers (ctrl-c to stop)"
        )

        count = 0
        async with KalshiAdapter(settings) as adapter:
            async for event in adapter.connect(tickers):
                count += 1
                console.print(
                    f"[dim]{count}[/dim] "
                    f"[cyan]{event.event_type.value}[/cyan] "
                    f"new={event.new_value} "
                    f"{event.metadata or ''}"
                )

    try:
        asyncio.run(_stream())
    except KeyboardInterrupt:
        console.print("\nStream stopped.")


if __name__ == "__main__":
    app()
