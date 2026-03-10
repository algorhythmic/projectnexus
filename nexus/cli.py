"""Command-line interface for Nexus."""

import asyncio
import contextlib
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List

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

def _build_adapters(platform: str = "all") -> List:
    """Build adapter list based on platform selection."""
    from nexus.adapters.kalshi import KalshiAdapter
    from nexus.adapters.polymarket import PolymarketAdapter

    adapters: List = []
    if platform in ("all", "kalshi"):
        adapters.append(KalshiAdapter(settings))
    if platform in ("all", "polymarket") and settings.polymarket_enabled:
        adapters.append(PolymarketAdapter(settings))
    return adapters


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
    table.add_row("Polymarket Enabled", str(settings.polymarket_enabled))
    table.add_row("Polymarket URL", settings.polymarket_base_url)
    table.add_row("Store Backend", settings.store_backend)
    if settings.store_backend == "postgres":
        table.add_row("Postgres DSN", settings.postgres_dsn.split("@")[-1] if settings.postgres_dsn else "(not set)")
        table.add_row("PG Pool", f"{settings.postgres_pool_min}-{settings.postgres_pool_max}")
    else:
        table.add_row("SQLite Path", settings.sqlite_path)
    table.add_row("Discovery Interval", f"{settings.discovery_interval_seconds}s")
    table.add_row("Rate Limit", f"{settings.kalshi_reads_per_second} reads/sec")

    console.print(table)


@app.command(name="db-init")
def db_init() -> None:
    """Initialize the event store (create tables)."""
    from nexus.store import create_store

    async def _init() -> None:
        store = create_store(settings)
        await store.initialize()
        await store.close()

    asyncio.run(_init())
    backend = settings.store_backend
    location = settings.postgres_dsn.split("@")[-1] if backend == "postgres" else settings.sqlite_path
    console.print(f"Database initialized ({backend}) at [bold]{location}[/bold]")


@app.command(name="db-stats")
def db_stats() -> None:
    """Show event store statistics."""
    from nexus.store import create_store

    async def _stats() -> dict:
        store = create_store(settings)
        await store.initialize()
        mc = await store.get_market_count()
        ec = await store.get_event_count()
        dist = await store.get_event_type_distribution()
        min_ts, max_ts = await store.get_event_time_range()
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
    backend = settings.store_backend
    location = settings.postgres_dsn.split("@")[-1] if backend == "postgres" else settings.sqlite_path
    table.add_row("Database", f"{backend}: {location}")
    if data["min_ts"] and data["max_ts"]:
        duration_h = (data["max_ts"] - data["min_ts"]) / 1000 / 3600
        table.add_row("Time span", f"{duration_h:.1f} hours")
        table.add_row("First event", _format_ms_timestamp(data["min_ts"]))
        table.add_row("Last event", _format_ms_timestamp(data["max_ts"]))
    for event_type, count in (data["distribution"] or {}).items():
        table.add_row(f"  {event_type}", str(count))
    console.print(table)


@app.command()
def discover(
    platform: str = typer.Option("all", help="Platform: kalshi, polymarket, or all"),
) -> None:
    """Run a single discovery cycle (one-shot, no loop)."""
    from nexus.ingestion.discovery import DiscoveryLoop
    from nexus.store import create_store

    async def _discover() -> None:
        store = create_store(settings)
        await store.initialize()

        adapters = _build_adapters(platform)
        if not adapters:
            console.print("[bold red]No adapters configured.[/bold red]")
            await store.close()
            return

        async with contextlib.AsyncExitStack() as stack:
            for a in adapters:
                await stack.enter_async_context(a)

            loop = DiscoveryLoop(
                adapters=adapters,
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
def run(
    platform: str = typer.Option("all", help="Platform: kalshi, polymarket, or all"),
) -> None:
    """Start real-time ingestion (REST discovery + WebSocket streaming)."""
    from nexus.ingestion.bus import EventBus
    from nexus.ingestion.manager import IngestionManager
    from nexus.ingestion.metrics import MetricsCollector
    from nexus.store import create_store

    async def _run() -> None:
        store = create_store(settings)
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

        adapters = _build_adapters(platform)
        if not adapters:
            console.print("[bold red]No adapters configured.[/bold red]")
            await bus.stop()
            await store.close()
            return

        async with contextlib.AsyncExitStack() as stack:
            for a in adapters:
                await stack.enter_async_context(a)

            manager = IngestionManager(
                adapters, store, bus, settings, metrics=metrics
            )
            console.print(
                f"Starting ingestion ({len(adapters)} adapter(s), discovery every "
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
def poll(
    platform: str = typer.Option("all", help="Platform: kalshi, polymarket, or all"),
) -> None:
    """Start discovery-only polling loop (no WebSocket)."""
    from nexus.ingestion.discovery import DiscoveryLoop
    from nexus.store import create_store

    async def _poll() -> None:
        store = create_store(settings)
        await store.initialize()

        adapters = _build_adapters(platform)
        if not adapters:
            console.print("[bold red]No adapters configured.[/bold red]")
            await store.close()
            return

        async with contextlib.AsyncExitStack() as stack:
            for a in adapters:
                await stack.enter_async_context(a)

            loop = DiscoveryLoop(
                adapters=adapters,
                store=store,
                interval_seconds=settings.discovery_interval_seconds,
            )
            console.print(
                f"Polling {len(adapters)} adapter(s) every "
                f"{settings.discovery_interval_seconds}s (ctrl-c to stop)"
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
def stream(
    platform: str = typer.Option("kalshi", help="Platform: kalshi or polymarket"),
) -> None:
    """Stream WebSocket events to console (debug tool, no storage)."""
    from nexus.store import create_store

    async def _stream() -> None:
        store = create_store(settings)
        await store.initialize()
        markets = await store.get_active_markets(platform=platform)
        tickers = [m.external_id for m in markets]
        await store.close()

        if not tickers:
            console.print(
                f"[bold red]No {platform} markets found.[/bold red] "
                f"Run [cyan]nexus discover --platform {platform}[/cyan] first."
            )
            return

        adapters = _build_adapters(platform)
        if not adapters:
            console.print("[bold red]No adapter for platform.[/bold red]")
            return

        adapter = adapters[0]
        console.print(
            f"Streaming {len(tickers)} {platform} tickers (ctrl-c to stop)"
        )

        count = 0
        async with adapter:
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
    from nexus.store import create_store

    async def _validate() -> None:
        store = create_store(settings)
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

        min_ts, max_ts = await store.get_event_time_range()
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


@app.command()
def detect() -> None:
    """Run a single anomaly detection cycle (includes cluster correlation)."""
    from nexus.correlation.detection_loop import DetectionLoop
    from nexus.store import create_store

    async def _detect() -> None:
        store = create_store(settings)
        await store.initialize()

        loop = DetectionLoop(
            store=store,
            window_configs=settings.anomaly_window_configs,
            baseline_hours=settings.anomaly_baseline_hours,
            expiry_hours=settings.anomaly_expiry_hours,
            cluster_min_markets=settings.cluster_anomaly_min_markets,
            cluster_window_minutes=settings.cluster_anomaly_window_minutes,
            cross_platform_enabled=settings.cross_platform_enabled,
            cross_platform_window_minutes=settings.cross_platform_window_minutes,
            retention_days=settings.retention_days,
        )
        count = await loop.run_once()
        await store.close()

        console.print(f"Detection complete: {count} anomalies found")

    asyncio.run(_detect())


@app.command()
def anomalies(
    since_hours: int = typer.Option(24, help="Show anomalies from last N hours"),
    min_severity: float = typer.Option(0.0, help="Minimum severity threshold"),
    status: str = typer.Option("", help="Filter by status (active/expired/acknowledged)"),
    anomaly_type: str = typer.Option("", help="Filter by type (single_market/cluster/cross_platform)"),
    limit: int = typer.Option(50, help="Max anomalies to show"),
) -> None:
    """List recent anomalies."""
    from nexus.core.types import AnomalyStatus
    from nexus.store import create_store

    async def _anomalies() -> None:
        store = create_store(settings)
        await store.initialize()

        since = int((time.time() - since_hours * 3600) * 1000) if since_hours > 0 else None
        status_filter = AnomalyStatus(status) if status else None

        results = await store.get_anomalies(
            since=since,
            min_severity=min_severity if min_severity > 0 else None,
            status=status_filter,
            anomaly_type=anomaly_type if anomaly_type else None,
            limit=limit,
        )
        await store.close()

        if not results:
            console.print("No anomalies found.")
            return

        table = Table(title=f"Anomalies (last {since_hours}h)")
        table.add_column("ID", style="dim")
        table.add_column("Detected", style="cyan")
        table.add_column("Type", style="blue")
        table.add_column("Severity", style="yellow")
        table.add_column("Markets", style="green")
        table.add_column("Summary")
        table.add_column("Status", style="bold")

        for a in results:
            sev_style = "red" if a.severity >= 0.7 else "yellow" if a.severity >= 0.4 else "green"
            summary_text = (a.summary or "")[:60]
            # For cluster anomalies, show cluster name from metadata
            if a.anomaly_type.value == "cluster" and a.metadata:
                import json as _json
                try:
                    meta = _json.loads(a.metadata)
                    cname = meta.get("cluster_name", "")
                    if cname:
                        summary_text = f"[{cname}] {summary_text}"[:60]
                except (ValueError, TypeError):
                    pass
            table.add_row(
                str(a.id),
                _format_ms_timestamp(a.detected_at),
                a.anomaly_type.value,
                f"[{sev_style}]{a.severity:.2f}[/{sev_style}]",
                str(a.market_count),
                summary_text,
                a.status.value,
            )

        console.print(table)

    asyncio.run(_anomalies())


@app.command(name="anomaly-stats")
def anomaly_stats(
    hours: int = typer.Option(24, help="Analysis window in hours"),
) -> None:
    """Show anomaly signal quality statistics."""
    from nexus.store import create_store

    async def _stats() -> None:
        store = create_store(settings)
        await store.initialize()

        now_ms = int(time.time() * 1000)
        since = now_ms - (hours * 3600 * 1000)
        results = await store.get_anomalies(since=since, limit=10000)
        await store.close()

        total = len(results)
        alerts_per_day = total / max(hours / 24, 1)

        table = Table(title=f"Anomaly Statistics (last {hours}h)")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")
        table.add_column("Status", style="bold")

        table.add_row(
            "Total anomalies", str(total), ""
        )
        table.add_row(
            "Alerts/day rate",
            f"{alerts_per_day:.1f}",
            "[green]PASS[/green]" if alerts_per_day < 50 else "[yellow]HIGH[/yellow]",
        )

        # Severity distribution
        high = sum(1 for a in results if a.severity >= 0.7)
        medium = sum(1 for a in results if 0.4 <= a.severity < 0.7)
        low = sum(1 for a in results if a.severity < 0.4)
        table.add_row("High severity (>=0.7)", str(high), "")
        table.add_row("Medium severity (0.4-0.7)", str(medium), "")
        table.add_row("Low severity (<0.4)", str(low), "")

        console.print(table)

        # Decision Gate
        console.print()
        if alerts_per_day < 50:
            console.print("[bold green]DECISION GATE (alert rate): PASS[/bold green]")
        else:
            console.print("[bold yellow]DECISION GATE (alert rate): NOT MET[/bold yellow]")
            console.print(f"  Target: < 50/day, Current: {alerts_per_day:.1f}/day")

    asyncio.run(_stats())


@app.command()
def correlate() -> None:
    """Run a single cluster correlation cycle (standalone, no single-market detection)."""
    from nexus.correlation.correlator import ClusterCorrelator
    from nexus.store import create_store

    async def _correlate() -> None:
        store = create_store(settings)
        await store.initialize()

        correlator = ClusterCorrelator(
            store,
            min_cluster_markets=settings.cluster_anomaly_min_markets,
            cluster_window_minutes=settings.cluster_anomaly_window_minutes,
        )
        now_ms = int(time.time() * 1000)
        count = await correlator.correlate_and_store(now_ms)
        await store.close()

        console.print(f"Correlation complete: {count} cluster anomalies found")

    asyncio.run(_correlate())


@app.command(name="signal-report")
def signal_report(
    days: int = typer.Option(7, help="Analysis window in days"),
) -> None:
    """Show Decision Gate signal analysis for cluster correlation."""
    from nexus.core.types import AnomalyType
    from nexus.store import create_store

    async def _report() -> None:
        store = create_store(settings)
        await store.initialize()

        now_ms = int(time.time() * 1000)
        since = now_ms - (days * 24 * 3600 * 1000)

        all_anomalies = await store.get_anomalies(since=since, limit=100000)
        single = [a for a in all_anomalies if a.anomaly_type == AnomalyType.SINGLE_MARKET]
        cluster_list = [a for a in all_anomalies if a.anomaly_type == AnomalyType.CLUSTER]

        total = len(all_anomalies)
        alerts_per_day = total / max(days, 1)
        cluster_per_day = len(cluster_list) / max(days, 1)

        # Summary table
        table = Table(title=f"Signal Report (last {days} days)")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")
        table.add_column("Status", style="bold")

        table.add_row("Total anomalies", str(total), "")
        table.add_row("Single-market", str(len(single)), "")
        table.add_row("Cluster", str(len(cluster_list)), "")
        table.add_row(
            "Total alerts/day",
            f"{alerts_per_day:.1f}",
            "[green]PASS[/green]" if alerts_per_day < 50 else "[red]FAIL[/red]",
        )
        table.add_row("Cluster alerts/day", f"{cluster_per_day:.1f}", "")

        # Severity distribution
        high = sum(1 for a in all_anomalies if a.severity >= 0.7)
        medium = sum(1 for a in all_anomalies if 0.4 <= a.severity < 0.7)
        low = sum(1 for a in all_anomalies if a.severity < 0.4)
        table.add_row("High severity (>=0.7)", str(high), "")
        table.add_row("Medium (0.4-0.7)", str(medium), "")
        table.add_row("Low (<0.4)", str(low), "")

        console.print(table)

        # Cluster anomaly detail table
        if cluster_list:
            import json as _json

            detail = Table(title="Cluster Anomaly Details")
            detail.add_column("ID", style="dim")
            detail.add_column("Detected", style="cyan")
            detail.add_column("Cluster", style="blue")
            detail.add_column("Markets", style="green")
            detail.add_column("Direction", style="yellow")
            detail.add_column("Severity", style="red")
            detail.add_column("Catalyst?", style="dim")

            for a in cluster_list:
                cluster_name = ""
                direction = ""
                if a.metadata:
                    try:
                        meta = _json.loads(a.metadata)
                        cluster_name = meta.get("cluster_name", "")
                        direction = meta.get("direction", "")
                    except (ValueError, TypeError):
                        pass
                detail.add_row(
                    str(a.id),
                    _format_ms_timestamp(a.detected_at),
                    cluster_name,
                    str(a.market_count),
                    direction,
                    f"{a.severity:.2f}",
                    "[ ]",
                )

            console.print(detail)

        # Decision Gate
        console.print()
        rate_ok = alerts_per_day < 50
        if rate_ok:
            console.print("[bold green]DECISION GATE (< 50 alerts/day): PASS[/bold green]")
        else:
            console.print("[bold red]DECISION GATE (< 50 alerts/day): FAIL[/bold red]")
            console.print(f"  Current: {alerts_per_day:.1f}/day (target < 50)")

        console.print(
            "[bold yellow]DECISION GATE (> 60% signal quality): "
            "MANUAL VALIDATION REQUIRED[/bold yellow]"
        )
        console.print(
            "  Review cluster anomalies above and mark 'Catalyst?' column "
            "against news sources."
        )

        await store.close()

    asyncio.run(_report())


@app.command()
def cluster(
    mode: str = typer.Option("incremental", help="'batch' or 'incremental'"),
    dry_run: bool = typer.Option(False, help="Show unassigned count without calling LLM"),
) -> None:
    """Run topic clustering on unassigned markets."""
    from nexus.clustering.clusterer import TopicClusterer
    from nexus.clustering.llm_client import ClaudeClient
    from nexus.store import create_store

    async def _cluster() -> None:
        store = create_store(settings)
        await store.initialize()

        unassigned = await store.get_unassigned_markets()
        console.print(f"Unassigned markets: {len(unassigned)}")

        if dry_run:
            await store.close()
            return

        if not unassigned:
            console.print("Nothing to cluster.")
            await store.close()
            return

        try:
            client = ClaudeClient(settings)
        except ValueError as e:
            console.print(f"[bold red]Error:[/bold red] {e}")
            await store.close()
            return

        clusterer = TopicClusterer(store, client, settings)

        if mode == "batch":
            count = await clusterer.batch_cluster()
        else:
            count = await clusterer.incremental_cluster()

        cost = client.get_cost_summary()
        await client.close()
        await store.close()

        console.print(f"Assignments made: {count}")
        console.print(
            f"LLM cost: ${cost['total_cost_usd']:.4f} "
            f"({cost['total_requests']} calls, "
            f"{cost['total_input_tokens']} in / {cost['total_output_tokens']} out tokens)"
        )

    asyncio.run(_cluster())


@app.command()
def clusters(
    show_markets: bool = typer.Option(False, help="Show markets in each cluster"),
) -> None:
    """List all topic clusters."""
    from nexus.store import create_store

    async def _clusters() -> None:
        store = create_store(settings)
        await store.initialize()

        all_clusters = await store.get_clusters()
        if not all_clusters:
            console.print("No clusters found. Run [cyan]nexus cluster[/cyan] first.")
            await store.close()
            return

        table = Table(title="Topic Clusters")
        table.add_column("ID", style="dim")
        table.add_column("Name", style="cyan")
        table.add_column("Description")
        table.add_column("Markets", style="green")
        table.add_column("Created", style="dim")

        for c in all_clusters:
            markets = await store.get_cluster_markets(c.id)
            table.add_row(
                str(c.id),
                c.name,
                (c.description or "")[:50],
                str(len(markets)),
                _format_ms_timestamp(c.created_at),
            )

            if show_markets and markets:
                for mid, conf in markets:
                    m = await store.get_market_by_id(mid) if hasattr(store, 'get_market_by_id') else None
                    title = f"market_id={mid}" if m is None else m.title[:40]
                    table.add_row("", f"  {title}", "", f"{conf:.2f}", "")

        console.print(table)
        await store.close()

    asyncio.run(_clusters())


@app.command(name="cluster-stats")
def cluster_stats() -> None:
    """Show topic clustering quality statistics."""
    from nexus.store import create_store

    async def _stats() -> None:
        store = create_store(settings)
        await store.initialize()

        total_markets = await store.get_market_count()
        all_clusters = await store.get_clusters()
        unassigned = await store.get_unassigned_markets()
        assigned = total_markets - len(unassigned)

        table = Table(title="Clustering Statistics")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Total markets", str(total_markets))
        table.add_row("Assigned", str(assigned))
        table.add_row("Unassigned", str(len(unassigned)))
        table.add_row("Total clusters", str(len(all_clusters)))

        if all_clusters:
            sizes = []
            for c in all_clusters:
                markets = await store.get_cluster_markets(c.id)
                sizes.append(len(markets))
            table.add_row("Avg markets/cluster", f"{sum(sizes)/len(sizes):.1f}")
            table.add_row("Min markets/cluster", str(min(sizes)))
            table.add_row("Max markets/cluster", str(max(sizes)))

        console.print(table)
        await store.close()

    asyncio.run(_stats())


@app.command(name="db-migrate")
def db_migrate() -> None:
    """Migrate data from SQLite to PostgreSQL."""
    from nexus.store.sqlite import SQLiteStore

    if settings.store_backend != "postgres":
        console.print("[bold red]store_backend must be 'postgres' for migration.[/bold red]")
        raise typer.Exit(1)
    if not settings.postgres_dsn:
        console.print("[bold red]POSTGRES_DSN is not set.[/bold red]")
        raise typer.Exit(1)

    async def _migrate() -> None:
        from nexus.store.postgres import PostgresStore

        src = SQLiteStore(settings.sqlite_path)
        await src.initialize()
        dst = PostgresStore(
            dsn=settings.postgres_dsn,
            pool_min=settings.postgres_pool_min,
            pool_max=settings.postgres_pool_max,
        )
        await dst.initialize()

        # Migrate markets
        console.print("Migrating markets...")
        active = await src.get_active_markets()
        from nexus.core.types import DiscoveredMarket
        discovered = [
            DiscoveredMarket(
                platform=m.platform,
                external_id=m.external_id,
                title=m.title,
                description=m.description,
                category=m.category,
                is_active=m.is_active,
            )
            for m in active
        ]
        new_m = await dst.upsert_markets(discovered)
        console.print(f"  Markets migrated: {new_m} new, {len(active)} total")

        # Migrate events in batches
        console.print("Migrating events...")
        total_events = await src.get_event_count()
        batch_size = 5000
        migrated = 0
        # Get events in timestamp-ascending order using get_events
        offset_ts = 0
        while True:
            # Get a batch of events since offset
            events = await src.get_events(since=offset_ts, limit=batch_size)
            if not events:
                break
            # get_events returns DESC order, reverse for chronological
            events.reverse()
            inserted = await dst.insert_events(events)
            migrated += inserted
            # Move offset past the last event
            offset_ts = events[-1].timestamp + 1
            console.print(f"  {migrated}/{total_events} events migrated...")

        # Migrate clusters
        console.print("Migrating topic clusters...")
        clusters = await src.get_clusters()
        for c in clusters:
            await dst.insert_cluster(c)
            # Migrate memberships
            members = await src.get_cluster_markets(c.id)
            for mid, conf in members:
                # Look up market in destination by platform+external_id
                src_market = None
                for m in active:
                    if m.id == mid:
                        src_market = m
                        break
                if src_market:
                    dst_market = await dst.get_market_by_external_id(
                        src_market.platform.value, src_market.external_id
                    )
                    if dst_market and dst_market.id is not None:
                        await dst.assign_market_to_cluster(dst_market.id, c.id, conf)
        console.print(f"  Clusters migrated: {len(clusters)}")

        # Refresh materialized views
        console.print("Refreshing materialized views...")
        await dst.refresh_views(concurrently=False)

        await src.close()
        await dst.close()
        console.print("[bold green]Migration complete![/bold green]")

    asyncio.run(_migrate())


@app.command(name="refresh-views")
def refresh_views() -> None:
    """Refresh PostgreSQL materialized views."""
    if settings.store_backend != "postgres":
        console.print("[bold red]refresh-views requires store_backend='postgres'[/bold red]")
        raise typer.Exit(1)

    async def _refresh() -> None:
        from nexus.store.postgres import PostgresStore

        store = PostgresStore(
            dsn=settings.postgres_dsn,
            pool_min=settings.postgres_pool_min,
            pool_max=settings.postgres_pool_max,
        )
        await store.initialize()
        await store.refresh_views()
        await store.close()
        console.print("[bold green]Materialized views refreshed.[/bold green]")

    asyncio.run(_refresh())


@app.command(name="cross-platform")
def cross_platform() -> None:
    """Build cross-platform links and run cross-platform correlation."""
    from nexus.correlation.cross_platform import CrossPlatformCorrelator
    from nexus.store import create_store

    async def _xplat() -> None:
        store = create_store(settings)
        await store.initialize()

        correlator = CrossPlatformCorrelator(
            store=store,
            window_minutes=settings.cross_platform_window_minutes,
        )

        links = await correlator.build_links()
        console.print(f"Cross-platform links created/updated: {links}")

        now_ms = int(time.time() * 1000)
        count = await correlator.correlate_and_store(now_ms)
        console.print(f"Cross-platform anomalies detected: {count}")

        await store.close()

    asyncio.run(_xplat())


@app.command()
def prune(
    days: int = typer.Option(0, help="Delete events older than N days (0 = use config)"),
    dry_run: bool = typer.Option(False, help="Show what would be deleted without deleting"),
) -> None:
    """Prune old events from the event store."""
    from nexus.store import create_store

    retention = days if days > 0 else settings.retention_days
    if retention <= 0:
        console.print("[bold red]No retention period set. Use --days or set RETENTION_DAYS.[/bold red]")
        raise typer.Exit(1)

    async def _prune() -> None:
        store = create_store(settings)
        await store.initialize()

        cutoff_ms = int((time.time() - retention * 86400) * 1000)
        total_events = await store.get_event_count()

        if dry_run:
            # Count events that would be pruned
            min_ts, max_ts = await store.get_event_time_range()
            if min_ts and min_ts < cutoff_ms:
                count = await store.get_event_count_in_range(min_ts, cutoff_ms - 1)
                console.print(
                    f"[yellow]Dry run:[/yellow] would delete {count} of {total_events} "
                    f"events older than {retention} days"
                )
            else:
                console.print(f"No events older than {retention} days to prune")
        else:
            pruned = await store.prune_events(cutoff_ms)
            console.print(
                f"Pruned {pruned} events older than {retention} days "
                f"({total_events - pruned} remaining)"
            )

        await store.close()

    asyncio.run(_prune())


@app.command()
def sync(
    once: bool = typer.Option(False, help="Run one sync cycle and exit"),
) -> None:
    """Start the Convex sync layer (PostgreSQL → Convex)."""
    if settings.store_backend != "postgres":
        console.print("[bold red]Sync requires store_backend='postgres'[/bold red]")
        raise typer.Exit(1)
    if not settings.convex_deployment_url or not settings.convex_deploy_key:
        console.print(
            "[bold red]CONVEX_DEPLOYMENT_URL and CONVEX_DEPLOY_KEY must be set.[/bold red]"
        )
        raise typer.Exit(1)

    async def _sync() -> None:
        from nexus.store.postgres import PostgresStore
        from nexus.sync import ConvexClient, SyncLayer

        store = PostgresStore(
            dsn=settings.postgres_dsn,
            pool_min=settings.postgres_pool_min,
            pool_max=settings.postgres_pool_max,
        )
        await store.initialize()

        convex = ConvexClient(
            deployment_url=settings.convex_deployment_url,
            deploy_key=settings.convex_deploy_key,
        )

        layer = SyncLayer(
            store=store,
            convex=convex,
            market_interval=settings.sync_market_interval_seconds,
            summary_interval=settings.sync_summary_interval_seconds,
            topics_interval=settings.sync_topics_interval_seconds,
        )

        if once:
            results = await layer.sync_all()
            console.print(f"Sync complete: {results}")
        else:
            console.print(
                f"Starting sync loop (markets: {settings.sync_market_interval_seconds}s, "
                f"summaries: {settings.sync_summary_interval_seconds}s, "
                f"topics: {settings.sync_topics_interval_seconds}s). Ctrl-c to stop."
            )
            try:
                await layer.run_forever()
            except asyncio.CancelledError:
                pass

        await convex.close()
        await store.close()

    try:
        asyncio.run(_sync())
    except KeyboardInterrupt:
        console.print("\nSync stopped.")


if __name__ == "__main__":
    app()
