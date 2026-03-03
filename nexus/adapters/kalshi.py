"""Kalshi prediction market adapter.

Implements the BaseAdapter interface for the Kalshi exchange.
Phase 1 (Milestone 1.1): REST-based market discovery with RSA-PSS auth.
Phase 1 (Milestone 1.2): WebSocket streaming (connect method).
"""

from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional

from nexus.adapters.auth import RSAPrivateKey, generate_auth_headers, load_private_key
from nexus.adapters.base import BaseAdapter
from nexus.core.config import Settings
from nexus.core.types import DiscoveredMarket, EventRecord, Platform

# Mapping of Kalshi categories to standardized names
_CATEGORY_MAP: Dict[str, str] = {
    "Economics": "Economics",
    "Politics": "Politics",
    "Elections": "Politics",
    "Weather": "Weather",
    "Sports": "Sports",
    "Entertainment": "Entertainment",
    "Technology": "Technology",
    "Science": "Science",
    "Business": "Business",
    "Crypto": "Cryptocurrency",
    "Cryptocurrency": "Cryptocurrency",
    "Climate": "Weather",
    "Financial": "Economics",
    "Culture": "Entertainment",
}


def _categorize_from_title(title: str) -> str:
    """Categorize a market based on title keywords."""
    t = title.lower()
    if any(w in t for w in ("election", "president", "congress", "senate", "vote", "poll")):
        return "Politics"
    if any(w in t for w in ("bitcoin", "crypto", "ethereum", "btc", "eth")):
        return "Cryptocurrency"
    if any(w in t for w in ("gdp", "inflation", "fed", "economy", "unemployment", "interest rate")):
        return "Economics"
    if any(w in t for w in ("nfl", "nba", "mlb", "nhl", "super bowl", "world cup")):
        return "Sports"
    if any(w in t for w in ("temperature", "weather", "hurricane", "rain")):
        return "Weather"
    if any(w in t for w in ("movie", "oscar", "emmy", "celebrity")):
        return "Entertainment"
    if any(w in t for w in ("stock", "company", "ipo", "earnings")):
        return "Business"
    return "Other"


def _standardize_category(raw: Optional[str], title: str) -> str:
    """Map a Kalshi category string to a standardized name."""
    if raw:
        clean = raw.strip().title()
        mapped = _CATEGORY_MAP.get(clean)
        if mapped:
            return mapped
    return _categorize_from_title(title)


def _calculate_yes_price(market: Dict[str, Any]) -> Optional[float]:
    """Extract the yes price from a Kalshi market object."""
    raw = (
        market.get("yes_ask")
        or market.get("yes_bid")
        or market.get("last_price")
    )
    if raw is None:
        return None
    price = float(raw)
    # Kalshi reports prices in cents (0-100); normalize to 0-1
    if price > 1.0:
        price /= 100.0
    return max(0.0, min(1.0, price))


class KalshiAdapter(BaseAdapter):
    """Adapter for the Kalshi prediction market exchange.

    Uses RSA-PSS signed authentication on every request.  Pagination
    is cursor-based (the ``cursor`` field in the response).
    """

    def __init__(self, settings: Settings) -> None:
        base_url = settings.effective_kalshi_url
        super().__init__(
            base_url=base_url,
            rate_limit=settings.kalshi_reads_per_second,
            timeout=settings.request_timeout,
        )
        self._api_key = settings.kalshi_api_key
        self._private_key: Optional[RSAPrivateKey] = None
        self._key_path = settings.kalshi_private_key_path

        # Load key if path is configured
        if self._key_path:
            try:
                self._private_key = load_private_key(self._key_path)
                self.logger.info("Kalshi RSA private key loaded")
            except Exception as exc:
                self.logger.warning(
                    "Could not load Kalshi private key — "
                    "requests will be unauthenticated",
                    error=str(exc),
                )

    # ------------------------------------------------------------------
    # Auth header override
    # ------------------------------------------------------------------

    def _build_headers(self, method: str, path: str) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self._private_key and self._api_key:
            auth = generate_auth_headers(
                api_key=self._api_key,
                private_key=self._private_key,
                method=method,
                path=path,
            )
            headers.update(auth)
        return headers

    # ------------------------------------------------------------------
    # discover()
    # ------------------------------------------------------------------

    async def discover(self) -> List[DiscoveredMarket]:
        """Enumerate all active markets via cursor-paginated REST calls."""
        all_markets: List[DiscoveredMarket] = []
        cursor: Optional[str] = None

        while True:
            params: Dict[str, Any] = {"limit": 200, "status": "open"}
            if cursor:
                params["cursor"] = cursor

            data = await self.make_request("GET", "markets", params=params)

            raw_markets = data.get("markets", [])
            if not raw_markets:
                break

            for raw in raw_markets:
                market = self._normalize(raw)
                if market is not None:
                    all_markets.append(market)

            cursor = data.get("cursor")
            if not cursor:
                break

        self.logger.info(
            "Kalshi discovery complete", markets_found=len(all_markets)
        )
        return all_markets

    # ------------------------------------------------------------------
    # connect() — Milestone 1.2 placeholder
    # ------------------------------------------------------------------

    async def connect(self) -> AsyncIterator[EventRecord]:
        """WebSocket streaming — implemented in Milestone 1.2."""
        raise NotImplementedError("WebSocket support is Milestone 1.2")
        yield  # type: ignore[misc]  # pragma: no cover

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _normalize(self, raw: Dict[str, Any]) -> Optional[DiscoveredMarket]:
        """Convert a raw Kalshi API market object to a DiscoveredMarket."""
        external_id = raw.get("ticker") or raw.get("id")
        title = raw.get("title")
        if not external_id or not title:
            return None

        # Filter: must be open and not past close time
        status = raw.get("status")
        if status not in ("active", "open", "initialized"):
            return None
        close_time = raw.get("close_time")
        if close_time:
            try:
                ct = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
                if ct <= datetime.now(timezone.utc):
                    return None
            except (ValueError, TypeError):
                pass

        yes_price = _calculate_yes_price(raw)
        no_price = (1.0 - yes_price) if yes_price is not None else None

        volume = raw.get("volume") or raw.get("open_interest") or 0
        category = _standardize_category(raw.get("category"), title)
        description = raw.get("subtitle") or raw.get("description") or ""

        return DiscoveredMarket(
            platform=Platform.KALSHI,
            external_id=str(external_id),
            title=title,
            description=description,
            category=category,
            is_active=True,
            yes_price=yes_price,
            no_price=no_price,
            volume=float(volume),
            end_date=close_time,
            raw_data=raw,
        )
