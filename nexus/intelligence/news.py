"""News provider for catalyst attribution context.

Fetches recent news headlines via Google News RSS to provide external
context when attributing anomaly catalysts.  Results are cached in
memory with a configurable TTL to avoid redundant fetches.
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html import unescape
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote_plus

import httpx

from nexus.core.logging import LoggerMixin


@dataclass
class NewsItem:
    """A single news article from an external source."""

    title: str
    source: str
    published_at: str  # ISO-ish string from RSS
    url: str
    snippet: str  # First portion of description


class NewsProvider(LoggerMixin):
    """Fetches recent news relevant to a market or topic.

    Uses Google News RSS (free, no API key required).  Results are
    cached per query string with a 30-minute TTL.
    """

    GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"

    def __init__(
        self,
        cache_ttl: float = 1800.0,  # 30 minutes
        max_results: int = 5,
        timeout: float = 10.0,
    ) -> None:
        self._cache: Dict[str, Tuple[float, List[NewsItem]]] = {}
        self._cache_ttl = cache_ttl
        self._max_results = max_results
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def search(
        self, query: str, hours_back: int = 6
    ) -> List[NewsItem]:
        """Search for recent news articles matching a query.

        Args:
            query: Search terms (e.g. market title or topic).
            hours_back: How far back to look (passed as ``when:Nh``
                to Google News). Default 6 hours.

        Returns:
            Up to ``max_results`` :class:`NewsItem` objects.
        """
        cache_key = f"{query}:{hours_back}"

        # Check cache
        if cache_key in self._cache:
            ts, items = self._cache[cache_key]
            if time.time() - ts < self._cache_ttl:
                return items

        items = await self._fetch_google_news(query, hours_back)
        self._cache[cache_key] = (time.time(), items)
        return items

    async def _fetch_google_news(
        self, query: str, hours_back: int
    ) -> List[NewsItem]:
        """Fetch and parse Google News RSS feed."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout)

        # Build URL with time filter
        q = f"{query} when:{hours_back}h"
        url = f"{self.GOOGLE_NEWS_RSS}?q={quote_plus(q)}&hl=en-US&gl=US&ceid=US:en"

        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
        except (httpx.HTTPError, httpx.RequestError):
            self.logger.debug("news_fetch_failed", query=query, exc_info=True)
            return []

        return self._parse_rss(resp.text)

    def _parse_rss(self, xml_text: str) -> List[NewsItem]:
        """Parse Google News RSS XML into NewsItem objects."""
        items: List[NewsItem] = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            self.logger.debug("news_rss_parse_failed")
            return []

        for item_el in root.iter("item"):
            if len(items) >= self._max_results:
                break

            title = item_el.findtext("title", "")
            link = item_el.findtext("link", "")
            pub_date = item_el.findtext("pubDate", "")
            description = item_el.findtext("description", "")

            # Google News embeds source in title as "Headline - Source"
            source = ""
            if " - " in title:
                parts = title.rsplit(" - ", 1)
                title = parts[0]
                source = parts[1] if len(parts) > 1 else ""

            # Clean HTML from description
            snippet = unescape(description)
            # Strip HTML tags
            while "<" in snippet and ">" in snippet:
                start = snippet.index("<")
                end = snippet.index(">", start)
                snippet = snippet[:start] + snippet[end + 1 :]
            snippet = snippet[:200].strip()

            items.append(NewsItem(
                title=title.strip(),
                source=source.strip(),
                published_at=pub_date.strip(),
                url=link.strip(),
                snippet=snippet,
            ))

        return items

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
