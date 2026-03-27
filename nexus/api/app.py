"""Starlette REST API for serving broadcast market data.

All endpoints serve pre-computed data from BroadcastCache — no database
queries per request.  The cache is populated by the SyncLayer refresh loop.
"""

import json
import time
from typing import Any, Dict, Optional

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from nexus.api.cache import BroadcastCache


def _json_response(
    data: Any,
    status_code: int = 200,
    max_age: int = 30,
    etag: Optional[str] = None,
) -> Response:
    """Return a JSON response with caching headers."""
    body = json.dumps(data, separators=(",", ":")).encode()
    headers: Dict[str, str] = {
        "Content-Type": "application/json",
        "Cache-Control": f"public, max-age={max_age}, stale-while-revalidate={max_age * 2}",
    }
    if etag:
        headers["ETag"] = f'"{etag}"'
    return Response(body, status_code=status_code, headers=headers)


def _cached_response(request: Request, cache: BroadcastCache, key: str) -> Optional[Response]:
    """Return a cached response with ETag/conditional support, or None if not cached."""
    entry = cache.get(key)
    if entry is None:
        return None

    # Conditional request — return 304 if client has current version
    if_none_match = request.headers.get("if-none-match", "").strip('"')
    if if_none_match and if_none_match == entry.etag:
        return Response(status_code=304, headers={"ETag": f'"{entry.etag}"'})

    headers = {
        "Content-Type": "application/json",
        "Cache-Control": f"public, max-age={entry.max_age}, stale-while-revalidate={entry.max_age * 2}",
        "ETag": f'"{entry.etag}"',
    }
    return Response(entry.json_bytes, status_code=200, headers=headers)


# ---------------------------------------------------------------------------
# Endpoint handlers
# ---------------------------------------------------------------------------

async def get_markets(request: Request) -> Response:
    cache: BroadcastCache = request.app.state.cache
    entry = cache.get("markets")
    if entry is None:
        return _json_response({"markets": [], "total": 0}, max_age=5)

    markets = entry.data
    # Server-side filtering on cached list
    platform = request.query_params.get("platform")
    search = request.query_params.get("search", "").lower()
    sort = request.query_params.get("sort", "rank_score")

    if platform:
        markets = [m for m in markets if m.get("platform") == platform]
    if search:
        markets = [m for m in markets if search in m.get("title", "").lower()]

    # Sort
    if sort == "rank_score":
        markets.sort(key=lambda m: m.get("rankScore") or 0, reverse=True)
    elif sort == "price":
        markets.sort(key=lambda m: m.get("lastPrice") or 0, reverse=True)
    elif sort == "volume":
        markets.sort(key=lambda m: m.get("volume") or 0, reverse=True)

    total = len(markets)

    # Pagination
    try:
        limit = int(request.query_params.get("limit", "100"))
    except ValueError:
        limit = 100
    try:
        offset = int(request.query_params.get("offset", "0"))
    except ValueError:
        offset = 0

    page = markets[offset : offset + limit]

    return _json_response(
        {"markets": page, "total": total, "offset": offset, "limit": limit},
        max_age=entry.max_age,
        etag=entry.etag,
    )


async def get_market_stats(request: Request) -> Response:
    cache: BroadcastCache = request.app.state.cache
    resp = _cached_response(request, cache, "market_stats")
    if resp is not None:
        return resp
    return _json_response(
        {"totalMarkets": 0, "activeMarkets": 0, "platformCounts": {}, "categoryCounts": {}},
        max_age=5,
    )


async def get_anomalies(request: Request) -> Response:
    cache: BroadcastCache = request.app.state.cache
    entry = cache.get("anomalies")
    if entry is None:
        return _json_response([], max_age=5)

    anomalies = entry.data

    # Filtering
    anomaly_type = request.query_params.get("anomaly_type")
    min_severity_str = request.query_params.get("min_severity")

    if anomaly_type:
        anomalies = [a for a in anomalies if a.get("anomalyType") == anomaly_type]
    if min_severity_str:
        try:
            min_sev = float(min_severity_str)
            anomalies = [a for a in anomalies if a.get("severity", 0) >= min_sev]
        except ValueError:
            pass

    try:
        limit = int(request.query_params.get("limit", "50"))
    except ValueError:
        limit = 50

    return _json_response(anomalies[:limit], max_age=entry.max_age, etag=entry.etag)


async def get_anomaly_stats(request: Request) -> Response:
    cache: BroadcastCache = request.app.state.cache
    resp = _cached_response(request, cache, "anomaly_stats")
    if resp is not None:
        return resp
    return _json_response(
        {"activeCount": 0, "avgSeverity": 0, "bySeverityBucket": {"high": 0, "medium": 0, "low": 0}},
        max_age=5,
    )


async def get_topics(request: Request) -> Response:
    cache: BroadcastCache = request.app.state.cache
    entry = cache.get("topics")
    if entry is None:
        return _json_response([], max_age=5)

    try:
        limit = int(request.query_params.get("limit", "20"))
    except ValueError:
        limit = 20

    return _json_response(entry.data[:limit], max_age=entry.max_age, etag=entry.etag)


async def get_candlesticks(request: Request) -> Response:
    ticker = request.path_params["ticker"]
    cache: BroadcastCache = request.app.state.cache
    store = request.app.state.store

    try:
        period = int(request.query_params.get("period", "60"))
    except ValueError:
        period = 60

    # Check per-ticker cache
    cache_key = f"candles:{ticker}:{period}"
    entry = cache.get(cache_key)
    if entry is not None:
        resp = _cached_response(request, cache, cache_key)
        if resp is not None:
            return resp

    candles = None
    markets_entry = cache.get("markets")
    market_id = None
    if markets_entry:
        market = next(
            (m for m in markets_entry.data if m.get("externalId") == ticker),
            None,
        )
        if market:
            market_id = market["marketId"]

    # Source 1: Pre-computed candles table (fastest, no aggregation)
    if market_id is not None and store is not None and hasattr(store, "get_candles"):
        try:
            rows = await store.get_candles(market_id, interval="1m", limit=500)
            if rows:
                candles = [
                    {
                        "time": r["open_ts"],
                        "open": r["open"],
                        "high": r["high"],
                        "low": r["low"],
                        "close": r["close"],
                        "volume": r.get("volume", 0),
                    }
                    for r in reversed(rows)  # DB returns newest first, chart needs oldest first
                ]
        except Exception:
            candles = None

    # Source 2: Legacy compute_candlesticks() from raw events (fallback)
    if not candles and market_id is not None and store is not None:
        if hasattr(store, "compute_candlesticks"):
            try:
                candles = await store.compute_candlesticks(
                    market_id, period_minutes=period
                )
            except Exception:
                candles = None

    # Source 3: Kalshi API (for markets we don't have events for)
    if not candles:
        adapter = getattr(request.app.state, "kalshi_adapter", None)
        if adapter and hasattr(adapter, "get_candlesticks"):
            try:
                raw = await adapter.get_candlesticks(ticker, period_interval=period)
                if raw:
                    candles = [
                        {
                            "time": int(c.get("period_begin", c.get("time", 0))),
                            "open": float(c.get("open", 0)),
                            "high": float(c.get("high", 0)),
                            "low": float(c.get("low", 0)),
                            "close": float(c.get("close", 0)),
                            "volume": float(c.get("volume", 0)),
                        }
                        for c in raw
                    ]
            except Exception:
                candles = None

    if candles is None:
        return _json_response([], max_age=10)

    # Cache the result for 60s
    cache.update(cache_key, candles, max_age=60)
    return _json_response(candles, max_age=60)


async def get_status(request: Request) -> Response:
    cache: BroadcastCache = request.app.state.cache
    status = cache.get_status()

    # Include ring buffer stats if available
    ring_buffer = getattr(request.app.state, "ring_buffer", None)
    if ring_buffer is not None:
        stats = ring_buffer.get_stats()
        status["ring_buffer"] = {
            "total_events": stats.total_events,
            "total_markets": stats.total_markets,
            "memory_estimate_mb": stats.memory_estimate_mb,
            "oldest_event_age_seconds": round(stats.oldest_event_age_seconds),
            "events_added_total": stats.events_added_total,
            "events_expired_total": stats.events_expired_total,
        }

    return _json_response(status, max_age=10)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(
    cache: BroadcastCache,
    store: Any = None,
    health_tracker: Any = None,
    kalshi_adapter: Any = None,
    ring_buffer: Any = None,
) -> Starlette:
    """Create the Starlette application with all routes."""
    routes = [
        Route("/api/v1/markets", get_markets),
        Route("/api/v1/markets/stats", get_market_stats),
        Route("/api/v1/anomalies", get_anomalies),
        Route("/api/v1/anomalies/stats", get_anomaly_stats),
        Route("/api/v1/topics", get_topics),
        Route("/api/v1/candlesticks/{ticker}", get_candlesticks),
        Route("/api/v1/status", get_status),
    ]

    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["GET"],
            allow_headers=["*"],
        ),
    ]

    app = Starlette(routes=routes, middleware=middleware)
    app.state.cache = cache
    app.state.store = store
    app.state.health_tracker = health_tracker
    app.state.kalshi_adapter = kalshi_adapter
    app.state.ring_buffer = ring_buffer
    return app
