"""LLM-powered narrative generation for anomaly catalyst attribution.

Passes structured CatalystAnalysis + recent news headlines to Claude
to produce a human-readable explanation of *why* a market moved.
This is the experimental condition for Hypothesis C — compared against
the template-based narratives from ``templates.py``.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

from nexus.core.logging import LoggerMixin
from nexus.intelligence.narrative import CatalystAnalysis
from nexus.intelligence.news import NewsItem


@dataclass
class NarrativeResult:
    """Structured output from LLM narrative generation."""

    headline: str
    narrative: str
    attributed_catalyst: str  # Best-guess catalyst (news headline, "technical", etc.)
    confidence: float  # 0-1
    news_sources: List[str]  # URLs of news cited
    model: str
    tokens_used: int  # input + output
    latency_ms: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# -- Prompt templates -------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a prediction market analyst explaining why a market moved.
Given the market data, trading signals, and recent news, produce:

1. **headline**: A one-line summary (max 100 chars)
2. **narrative**: A 3-5 sentence explanation of the most likely catalyst
3. **attributed_catalyst**: Your best single-line attribution (a news headline, "data release", "whale activity", "technical momentum", etc.)
4. **confidence**: 0.0-1.0 confidence in your attribution

Be specific. Reference concrete evidence from the trading data and news.
If no news explains the move, attribute it to technical/market factors.

Respond in JSON only — no markdown, no commentary:
{"headline": "...", "narrative": "...", "attributed_catalyst": "...", "confidence": 0.0}"""

_USER_TEMPLATE = """\
Market: {title}
Direction: {direction} ({magnitude}%)
Window: {window_minutes} minutes

Trading signals:
- {trade_count} trades, {trades_per_minute:.1f}/min
- Whale activity: {whale_pct:.0%} of volume
- Taker imbalance: {taker_buy_pct:.0%} buy-side
- Burst detected: {burst_detected} ({burst_duration:.0f}s, {burst_pct:.0%} of trades)
- Avg trade size: {avg_trade_size:.1f}

Recent news:
{news_block}

Market context:
- Category: {category}
- Series: {series_prefix} ({markets_in_series} markets)
- Hours to expiry: {hours_to_expiry}"""


class LLMNarrator(LoggerMixin):
    """Generates narrative explanations for anomalies using Claude."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 512,
    ) -> None:
        import anthropic

        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        # Cumulative cost tracking
        self._total_cost: float = 0.0
        self._total_requests: int = 0

    async def narrate(
        self,
        catalyst: CatalystAnalysis,
        market_title: str,
        news: List[NewsItem],
        window_minutes: int = 15,
    ) -> NarrativeResult:
        """Generate an LLM-powered narrative for an anomaly.

        Args:
            catalyst: Structured catalyst analysis from the detection pipeline.
            market_title: Human-readable market title.
            news: Recent news articles for context.
            window_minutes: Detection window size.

        Returns:
            Structured :class:`NarrativeResult`.
        """
        user_prompt = self._build_user_prompt(
            catalyst, market_title, news, window_minutes
        )

        start_ms = int(time.time() * 1000)

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except Exception:
            self.logger.debug("llm_narrate_failed", exc_info=True)
            raise

        latency_ms = int(time.time() * 1000) - start_ms

        content = response.content[0].text if response.content else ""
        tokens = (response.usage.input_tokens or 0) + (response.usage.output_tokens or 0)

        self._total_requests += 1
        # Sonnet pricing: $3/M input, $15/M output
        self._total_cost += (
            (response.usage.input_tokens or 0) * 3.0 / 1_000_000
            + (response.usage.output_tokens or 0) * 15.0 / 1_000_000
        )

        return self._parse_response(
            content, news, tokens, latency_ms
        )

    def get_cost_summary(self) -> Dict[str, Any]:
        return {
            "total_requests": self._total_requests,
            "total_cost_usd": round(self._total_cost, 6),
        }

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if hasattr(self._client, "_client"):
            await self._client._client.aclose()

    @staticmethod
    def _build_user_prompt(
        catalyst: CatalystAnalysis,
        title: str,
        news: List[NewsItem],
        window_minutes: int,
    ) -> str:
        """Build the user prompt from catalyst data and news."""
        if news:
            news_lines = []
            for i, n in enumerate(news[:5], 1):
                news_lines.append(f"{i}. [{n.source}] {n.title}")
                if n.snippet:
                    news_lines.append(f"   {n.snippet[:150]}")
            news_block = "\n".join(news_lines)
        else:
            news_block = "(No recent news found)"

        return _USER_TEMPLATE.format(
            title=title,
            direction=catalyst.direction,
            magnitude=f"{catalyst.magnitude_pct:.1%}",
            window_minutes=window_minutes,
            trade_count=catalyst.trade_count,
            trades_per_minute=catalyst.trades_per_minute,
            whale_pct=catalyst.whale_trade_pct,
            taker_buy_pct=catalyst.taker_buy_pct,
            burst_detected=catalyst.burst_detected,
            burst_duration=catalyst.burst_duration_seconds,
            burst_pct=catalyst.burst_trade_pct,
            avg_trade_size=catalyst.avg_trade_size,
            news_block=news_block,
            category=catalyst.category or "Unknown",
            series_prefix=catalyst.series_prefix or "N/A",
            markets_in_series=catalyst.markets_in_series,
            hours_to_expiry=catalyst.hours_to_expiry or "N/A",
        )

    def _parse_response(
        self,
        content: str,
        news: List[NewsItem],
        tokens: int,
        latency_ms: int,
    ) -> NarrativeResult:
        """Parse Claude's JSON response into a NarrativeResult."""
        try:
            # Strip markdown fences if present
            text = content.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            data = json.loads(text.strip())
        except (json.JSONDecodeError, IndexError):
            self.logger.debug("llm_response_parse_failed", content=content[:200])
            data = {}

        return NarrativeResult(
            headline=data.get("headline", "Analysis unavailable"),
            narrative=data.get("narrative", content[:500]),
            attributed_catalyst=data.get("attributed_catalyst", "unknown"),
            confidence=min(1.0, max(0.0, float(data.get("confidence", 0.5)))),
            news_sources=[n.url for n in news[:5] if n.url],
            model=self._model,
            tokens_used=tokens,
            latency_ms=latency_ms,
        )
