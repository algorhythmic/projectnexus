"""Async HTTP client for Convex mutations and queries."""

import logging
from typing import Any, Dict, List, Optional

import httpx

from nexus.core.logging import LoggerMixin

# Suppress httpx per-request INFO logs that flood structured pipeline output
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


class ConvexClient(LoggerMixin):
    """Calls Convex mutations/queries via the HTTP API.

    Uses the Convex deployment URL and deploy key for authentication.
    All writes go through mutations; reads through queries.

    Convex HTTP API format:
        POST {deployment_url}/api/mutation
        Header: Authorization: Convex {deploy_key}
        Body: { "path": "module:functionName", "args": {...}, "format": "json" }
    """

    def __init__(
        self,
        deployment_url: str,
        deploy_key: str,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = deployment_url.rstrip("/")
        self._deploy_key = deploy_key
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                headers={
                    "Authorization": f"Convex {self._deploy_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def mutation(
        self, function_path: str, args: Dict[str, Any]
    ) -> Any:
        """Call a Convex mutation.

        Args:
            function_path: Module:function path (e.g. "nexusSync:upsertMarkets")
            args: Arguments dict to pass to the mutation.

        Returns:
            The mutation's return value.

        Raises:
            ConvexError: If the mutation fails.
        """
        client = await self._ensure_client()
        url = f"{self._base_url}/api/mutation"
        body = {
            "path": function_path,
            "args": args,
            "format": "json",
        }

        try:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            self.logger.error(
                "convex_mutation_error",
                function=function_path,
                status=e.response.status_code,
                body=e.response.text[:500],
            )
            raise ConvexError(
                f"Mutation {function_path} failed: {e.response.status_code}"
            ) from e
        except httpx.RequestError as e:
            self.logger.error(
                "convex_request_error",
                function=function_path,
                error=str(e),
            )
            raise ConvexError(
                f"Request to Convex failed: {e}"
            ) from e

        if data.get("status") == "error":
            msg = data.get("errorMessage", "Unknown error")
            self.logger.error(
                "convex_mutation_rejected",
                function=function_path,
                error=msg,
            )
            raise ConvexError(f"Mutation {function_path} rejected: {msg}")

        return data.get("value")

    async def query(
        self, function_path: str, args: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Call a Convex query.

        Args:
            function_path: Module:function path (e.g. "etl:getMarketStats")
            args: Optional arguments dict.

        Returns:
            The query result.
        """
        client = await self._ensure_client()
        url = f"{self._base_url}/api/query"
        body = {
            "path": function_path,
            "args": args or {},
            "format": "json",
        }

        try:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            raise ConvexError(
                f"Query {function_path} failed: {e.response.status_code}"
            ) from e
        except httpx.RequestError as e:
            raise ConvexError(f"Request to Convex failed: {e}") from e

        if data.get("status") == "error":
            raise ConvexError(
                f"Query {function_path} rejected: {data.get('errorMessage')}"
            )

        return data.get("value")

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None


class ConvexError(Exception):
    """Error communicating with Convex."""
