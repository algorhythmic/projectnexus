"""Uvicorn server runner for the asyncio TaskGroup.

Runs the Starlette API as a coroutine alongside the pipeline tasks.
"""

from typing import Any, Optional

import uvicorn

from nexus.api.app import create_app
from nexus.api.cache import BroadcastCache


async def run_api_server(
    cache: BroadcastCache,
    store: Any = None,
    health_tracker: Any = None,
    kalshi_adapter: Any = None,
    ring_buffer: Any = None,
    host: str = "0.0.0.0",
    port: int = 8080,
) -> None:
    """Run the REST API server as an async coroutine.

    Designed to be added to an ``asyncio.TaskGroup`` alongside
    the ingestion, detection, and sync tasks.
    """
    app = create_app(
        cache=cache,
        store=store,
        health_tracker=health_tracker,
        kalshi_adapter=kalshi_adapter,
        ring_buffer=ring_buffer,
    )
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    await server.serve()
