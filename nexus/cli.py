"""Command-line interface for Nexus."""

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

import nexus
from nexus.core.config import settings


def _format_ms_timestamp(ts_ms: int) -> str:
    """Format a Unix-ms timestamp for display."""
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )

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

    async def _stats() -> dict:
        store = SQLiteStore(settings.sqlite_path)
        await store.initialize()
        mc = await store.get_market_count()
        ec = await store.get_event_count()
        dist = await store.get_event_type_distribution()
        # Get time range
        cursor = await store.db.execute(
            "SELECT MIN(timestamp), MAX(timestamp) FROM events"
        )
        row = await cursor.fetchone()
        min_ts, max_ts = (row[0], row[1]) if row else (None, None)
        await store.close()
        return {
            "markets": mc, "events": ec, "distribution": dist,
            "min_ts": min_ts, "max_ts": max_ts,
        }

    data = asyncio.run(_stats())

    table = Table(title="Event Store Statistics")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Markets", str(data["markets"]))
    table.add_row("Events", str(data["events"]))
    table.add_row("Database", settings.sqlite_path)
    if data["min_ts"] and data["max_ts"]:
        duration_h = (data["max_ts"] - data["min_ts"]) / 1000 / 3600
        table.add_row("Time span", f"{duration_h:.1f} hours")
        table.add_row("First event", _format_ms_timestamp(data["min_ts"]))
        table.add_row("Last event", _format_ms_timestamp(data["max_ts"]))
    for event_type, count in (data["distribution"] or {}).items():
        table.add_row(f"  {event_type}", str(count))
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
    from nexus.ingestion.metrics import MetricsCollector
    from nexus.store.sqlite import SQLiteStore

    async def _run() -> None:
        store = SQLiteStore(settings.sqlite_path)
        await store.initialize()

        metrics = MetricsCollector()

        bus = EventBus(
            store=store,
            max_size=settings.event_queue_max_size,
            batch_size=settings.event_batch_size,
            batch_timeout=settings.event_batch_timeout,
            metrics=metrics,
        )
        bus.start()

        async with KalshiAdapter(settings) as adapter:
            manager = IngestionManager(
                adapter, store, bus, settings, metrics=metrics
            )
            console.print(
                f"Starting ingestion (discovery every "
                f"{settings.discovery_interval_seconds}s + WebSocket streaming, "
                f"health reports every {settings.health_report_interval_seconds}s). "
                f"Ctrl-c to stop."
            )
            try:
                await manager.run()
            except asyncio.CancelledError:
                pass
            finally:
                await manager.stop()

        await bus.stop()
        snap = metrics.snapshot()
        console.print(
            f"Events written: {snap.total_events_written} | "
            f"Uptime: {snap.uptime_seconds:.0f}s | "
            f"WS reconnects: {snap.ws_reconnect_count}"
        )
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


@app.command()
def validate(
    gap_minutes: int = typer.Option(5, help="Gap threshold in minutes"),
    since_hours: int = typer.Option(0, help="Only check events from last N hours (0=all)"),
) -> None:
    """Run data integrity checks and evaluate the Decision Gate."""
    from nexus.store.sqlite import SQLiteStore

    async def _validate() -> None:
        store = SQLiteStore(settings.sqlite_path)
        await store.initialize()

        since = None
        if since_hours > 0:
            since = int((time.time() - since_hours * 3600) * 1000)

        total = await store.get_event_count()
        total_in_range = (
            await store.get_event_count_in_range(since) if since else total
        )
        duplicates = await store.get_duplicate_event_count(since=since)
        gaps = await store.get_event_gaps(
            gap_threshold_ms=gap_minutes * 60 * 1000, since=since
        )
        violations = await store.get_ordering_violations(since=since)
        distribution = await store.get_event_type_distribution(since=since)

        # Time range
        cursor = await store.db.execute(
            "SELECT MIN(timestamp), MAX(timestamp) FROM events"
        )
        row = await cursor.fetchone()
        min_ts, max_ts = (row[0], row[1]) if row else (None, None)
        await store.close()

        # Main report
        table = Table(title="Data Integrity Report")
        table.add_column("Check", style="cyan")
        table.add_column("Result", style="green")
        table.add_column("Status", style="bold")

        table.add_row(
            "Total events", str(total),
            "[green]PASS[/green]" if total >= 100_000 else "[yellow]WARN[/yellow]",
        )
        if since:
            table.add_row("Events in range", str(total_in_range), "INFO")
        if min_ts and max_ts:
            duration_h = (max_ts - min_ts) / 1000 / 3600
            table.add_row(
                "Duration", f"{duration_h:.1f} hours",
                "[green]PASS[/green]" if duration_h >= 72 else "[yellow]WARN[/yellow]",
            )
        table.add_row(
            "Duplicate events", str(duplicates),
            "[green]PASS[/green]" if duplicates == 0 else "[yellow]WARN[/yellow]",
        )
        table.add_row(
            f"Gaps (>{gap_minutes}min)", str(len(gaps)),
            "[green]PASS[/green]" if len(gaps) == 0 else "[yellow]WARN[/yellow]",
        )
        table.add_row(
            "Ordering violations", str(violations),
            "[green]PASS[/green]" if violations == 0 else "[yellow]WARN[/yellow]",
        )
        console.print(table)

        # Event type distribution
        if distribution:
            dist_table = Table(title="Event Type Distribution")
            dist_table.add_column("Type", style="cyan")
            dist_table.add_column("Count", style="green")
            for event_type, count in distribution.items():
                dist_table.add_row(event_type, str(count))
            console.print(dist_table)

        # Gap details
        if gaps:
            gap_table = Table(title=f"Detected Gaps (>{gap_minutes}min)")
            gap_table.add_column("Start", style="cyan")
            gap_table.add_column("End", style="cyan")
            gap_table.add_column("Duration", style="yellow")
            for start, end, duration in gaps[:20]:
                gap_table.add_row(
                    _format_ms_timestamp(start),
                    _format_ms_timestamp(end),
                    f"{duration / 1000:.0f}s",
                )
            if len(gaps) > 20:
                console.print(f"  ... and {len(gaps) - 20} more gaps")
            console.print(gap_table)

        # Decision Gate
        console.print()
        duration_ok = (
            min_ts is not None
            and max_ts is not None
            and (max_ts - min_ts) / 1000 / 3600 >= 72
        )
        gate_pass = total >= 100_000 and duration_ok
        if gate_pass:
            console.print("[bold green]DECISION GATE: PASS[/bold green]")
        else:
            console.print("[bold yellow]DECISION GATE: NOT YET MET[/bold yellow]")
            if total < 100_000:
                console.print(f"  Need {100_000 - total:,} more events")
            if not duration_ok:
                hours = (
                    (max_ts - min_ts) / 1000 / 3600
                    if min_ts and max_ts
                    else 0
                )
                console.print(
                    f"  Need {72 - hours:.1f} more hours of runtime"
                )

    asyncio.run(_validate())


if __name__ == "__main__":
    app()
