"""Abstract base adapter for prediction market platforms."""

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence

import httpx

from nexus.core.logging import LoggerMixin
from nexus.core.types import DiscoveredMarket, EventRecord


class RateLimiter:
    """Simple async rate limiter for API calls."""

    def __init__(self, calls_per_second: float) -> None:
        self.calls_per_second = calls_per_second
        self.min_interval = 1.0 / calls_per_second
        self.last_call_time = 0.0

    async def acquire(self) -> None:
        """Wait if necessary to respect rate limits."""
        now = time.time()
        elapsed = now - self.last_call_time
        if elapsed < self.min_interval:
            await asyncio.sleep(self.min_interval - elapsed)
        self.last_call_time = time.time()


class BaseAdapter(LoggerMixin, ABC):
    """Abstract base class for platform adapters.

    Every prediction market platform is accessed through an adapter
    implementing this interface.  Two responsibilities:

    - discover(): REST polling to enumerate markets and detect new ones.
    - connect(): WebSocket subscription for real-time event streaming
      (Milestone 1.2).
    """

    def __init__(
        self,
        base_url: str,
        rate_limit: float = 10.0,
        timeout: int = 30,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._rate_limiter = RateLimiter(rate_limit)
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff_factor = backoff_factor
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Lazy-initialized HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout),
                limits=httpx.Limits(
                    max_connections=20, max_keepalive_connections=5
                ),
            )
        return self._client

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "BaseAdapter":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    async def discover(self) -> List[DiscoveredMarket]:
        """Discover markets via REST API polling.

        Returns a list of normalized market metadata from the platform.
        Called periodically by the discovery polling loop.
        """
        ...

    @abstractmethod
    async def connect(
        self, tickers: Sequence[str]
    ) -> AsyncIterator[EventRecord]:
        """Open a WebSocket connection and yield normalized events.

        Args:
            tickers: Market tickers to subscribe to.
        """
        ...
        # Unreachable, but satisfies the async iterator type.
        yield  # type: ignore[misc]  # pragma: no cover

    # ------------------------------------------------------------------
    # HTTP helpers (ported from ETL BaseExtractor)
    # ------------------------------------------------------------------

    def _build_headers(self, method: str, path: str) -> Dict[str, str]:
        """Build request headers.  Subclasses override for auth."""
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def make_request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Make an HTTP request with rate limiting and retry."""
        await self._rate_limiter.acquire()
        url = f"{self._base_url}/{path.lstrip('/')}"
        headers = self._build_headers(method.upper(), f"/{path.lstrip('/')}")

        for attempt in range(self._max_retries + 1):
            try:
                self.logger.debug(
                    "HTTP request",
                    method=method,
                    url=url,
                    attempt=attempt + 1,
                )
                resp = await self.client.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json_body,
                )
                resp.raise_for_status()
                return resp.json()

            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                self.logger.warning(
                    "HTTP error",
                    status=status,
                    url=url,
                    attempt=attempt + 1,
                )
                # Don't retry client errors (except 429)
                if 400 <= status < 500 and status != 429:
                    raise
                if attempt == self._max_retries:
                    raise
                wait = self._backoff_factor ** attempt
                await asyncio.sleep(wait)

            except Exception as exc:
                self.logger.error(
                    "Request failed",
                    error=str(exc),
                    url=url,
                    attempt=attempt + 1,
                )
                if attempt == self._max_retries:
                    raise
                wait = self._backoff_factor ** attempt
                await asyncio.sleep(wait)

        # Unreachable, but keeps mypy happy
        raise RuntimeError("Exhausted retries")  # pragma: no cover
