"""Tests for the LLMNarrator (Milestone 5.3)."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.intelligence.llm_narrator import LLMNarrator, NarrativeResult, _SYSTEM_PROMPT
from nexus.intelligence.narrative import CatalystAnalysis
from nexus.intelligence.news import NewsItem


def _make_analysis(**overrides) -> CatalystAnalysis:
    defaults = {
        "direction": "up",
        "magnitude_pct": 0.10,
        "price_from": 0.40,
        "price_to": 0.50,
        "trade_count": 5,
        "trades_per_minute": 1.0,
        "whale_trade_pct": 0.3,
        "taker_buy_pct": 0.6,
        "avg_trade_size": 10.0,
        "burst_detected": False,
        "burst_duration_seconds": 0.0,
        "burst_trade_pct": 0.0,
        "category": "Crypto",
        "series_prefix": "BTC",
        "hours_to_expiry": None,
        "markets_in_series": 5,
        "confidence": 0.5,
        "catalyst_type": "unknown",
    }
    defaults.update(overrides)
    return CatalystAnalysis(**defaults)


def _make_news(n: int = 2) -> list:
    return [
        NewsItem(
            title=f"News headline {i}",
            source=f"Source {i}",
            published_at="2026-03-24T12:00:00Z",
            url=f"https://example.com/news/{i}",
            snippet=f"Article snippet {i}",
        )
        for i in range(n)
    ]


class TestPromptBuilding:
    def test_builds_user_prompt_with_news(self):
        analysis = _make_analysis()
        news = _make_news(2)
        prompt = LLMNarrator._build_user_prompt(analysis, "BTC 100k", news, 15)
        assert "BTC 100k" in prompt
        assert "News headline 0" in prompt
        assert "Source 0" in prompt
        assert "up" in prompt

    def test_builds_user_prompt_without_news(self):
        analysis = _make_analysis()
        prompt = LLMNarrator._build_user_prompt(analysis, "Test Market", [], 60)
        assert "No recent news found" in prompt
        assert "Test Market" in prompt

    def test_includes_trading_signals(self):
        analysis = _make_analysis(trade_count=20, whale_trade_pct=0.6)
        prompt = LLMNarrator._build_user_prompt(analysis, "Test", [], 15)
        assert "20 trades" in prompt
        assert "60%" in prompt

    def test_system_prompt_requests_json(self):
        assert "JSON" in _SYSTEM_PROMPT


class TestResponseParsing:
    def test_parses_valid_json(self):
        narrator = LLMNarrator.__new__(LLMNarrator)
        narrator._model = "test-model"
        content = json.dumps({
            "headline": "BTC surges on whale buying",
            "narrative": "Large trades drove BTC higher.",
            "attributed_catalyst": "Whale accumulation",
            "confidence": 0.75,
        })
        result = narrator._parse_response(content, _make_news(1), 500, 200)
        assert result.headline == "BTC surges on whale buying"
        assert result.confidence == 0.75
        assert result.model == "test-model"
        assert result.tokens_used == 500
        assert len(result.news_sources) == 1

    def test_handles_markdown_fenced_json(self):
        narrator = LLMNarrator.__new__(LLMNarrator)
        narrator._model = "test"
        content = '```json\n{"headline": "Test", "narrative": "N", "attributed_catalyst": "C", "confidence": 0.5}\n```'
        result = narrator._parse_response(content, [], 100, 50)
        assert result.headline == "Test"

    def test_handles_invalid_json(self):
        narrator = LLMNarrator.__new__(LLMNarrator)
        narrator._model = "test"
        result = narrator._parse_response("not json at all", [], 100, 50)
        assert result.headline == "Analysis unavailable"
        assert "not json" in result.narrative

    def test_clamps_confidence(self):
        narrator = LLMNarrator.__new__(LLMNarrator)
        narrator._model = "test"
        content = json.dumps({
            "headline": "X", "narrative": "Y",
            "attributed_catalyst": "Z", "confidence": 5.0,
        })
        result = narrator._parse_response(content, [], 100, 50)
        assert result.confidence == 1.0


class TestNarrativeResult:
    def test_to_dict(self):
        result = NarrativeResult(
            headline="Test",
            narrative="Test narrative",
            attributed_catalyst="whale",
            confidence=0.7,
            news_sources=["http://x"],
            model="claude-sonnet",
            tokens_used=500,
            latency_ms=200,
        )
        d = result.to_dict()
        assert d["headline"] == "Test"
        assert d["model"] == "claude-sonnet"
        assert d["tokens_used"] == 500

    def test_cost_tracking(self):
        narrator = LLMNarrator.__new__(LLMNarrator)
        narrator._total_cost = 0.0
        narrator._total_requests = 0
        summary = narrator.get_cost_summary()
        assert summary["total_requests"] == 0
        assert summary["total_cost_usd"] == 0.0
