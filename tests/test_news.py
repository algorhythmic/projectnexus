"""Tests for the NewsProvider (Milestone 5.3)."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.intelligence.news import NewsItem, NewsProvider

SAMPLE_RSS = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>Test News</title>
<item>
  <title>Bitcoin surges past $100k - CoinDesk</title>
  <link>https://example.com/btc-surge</link>
  <pubDate>Mon, 24 Mar 2026 12:00:00 GMT</pubDate>
  <description>Bitcoin hit a new all-time high today, crossing $100k for the first time.</description>
</item>
<item>
  <title>Fed holds rates steady - Reuters</title>
  <link>https://example.com/fed-rates</link>
  <pubDate>Mon, 24 Mar 2026 11:30:00 GMT</pubDate>
  <description>The Federal Reserve maintained its benchmark rate at 5.25%.</description>
</item>
<item>
  <title>No source here</title>
  <link>https://example.com/no-source</link>
  <pubDate>Mon, 24 Mar 2026 11:00:00 GMT</pubDate>
  <description>An article &lt;b&gt;with HTML&lt;/b&gt; tags.</description>
</item>
</channel>
</rss>"""


class TestRSSParsing:
    def test_parses_items(self):
        provider = NewsProvider()
        items = provider._parse_rss(SAMPLE_RSS)
        assert len(items) == 3

    def test_extracts_title_and_source(self):
        provider = NewsProvider()
        items = provider._parse_rss(SAMPLE_RSS)
        assert items[0].title == "Bitcoin surges past $100k"
        assert items[0].source == "CoinDesk"

    def test_no_source_in_title(self):
        provider = NewsProvider()
        items = provider._parse_rss(SAMPLE_RSS)
        assert items[2].title == "No source here"
        assert items[2].source == ""

    def test_strips_html_from_description(self):
        provider = NewsProvider()
        items = provider._parse_rss(SAMPLE_RSS)
        assert "<b>" not in items[2].snippet
        assert "with HTML" in items[2].snippet

    def test_extracts_url(self):
        provider = NewsProvider()
        items = provider._parse_rss(SAMPLE_RSS)
        assert items[0].url == "https://example.com/btc-surge"

    def test_respects_max_results(self):
        provider = NewsProvider(max_results=2)
        items = provider._parse_rss(SAMPLE_RSS)
        assert len(items) == 2

    def test_handles_invalid_xml(self):
        provider = NewsProvider()
        items = provider._parse_rss("not xml at all")
        assert items == []

    def test_handles_empty_feed(self):
        provider = NewsProvider()
        items = provider._parse_rss(
            '<?xml version="1.0"?><rss><channel></channel></rss>'
        )
        assert items == []


class TestCaching:
    async def test_cache_hit(self):
        provider = NewsProvider(cache_ttl=300)
        # Pre-populate cache
        cached = [NewsItem("Test", "Src", "now", "http://x", "snip")]
        provider._cache["btc:6"] = (time.time(), cached)

        result = await provider.search("btc", hours_back=6)
        assert result == cached

    async def test_cache_expired(self):
        provider = NewsProvider(cache_ttl=1)
        cached = [NewsItem("Old", "Src", "old", "http://x", "snip")]
        provider._cache["btc:6"] = (time.time() - 10, cached)

        # Mock the HTTP fetch
        provider._fetch_google_news = AsyncMock(return_value=[
            NewsItem("New", "Src", "new", "http://y", "fresh")
        ])

        result = await provider.search("btc", hours_back=6)
        assert result[0].title == "New"
        provider._fetch_google_news.assert_called_once()
