"""Tests for the TemplateRenderer (Milestone 5.1)."""

import pytest

from nexus.intelligence.narrative import CatalystAnalysis
from nexus.intelligence.templates import TemplateRenderer


@pytest.fixture
def renderer():
    return TemplateRenderer()


def _make_analysis(**overrides) -> CatalystAnalysis:
    defaults = {
        "direction": "up",
        "magnitude_pct": 0.10,
        "price_from": 0.40,
        "price_to": 0.50,
        "trade_count": 5,
        "trades_per_minute": 1.0,
        "whale_trade_pct": 0.0,
        "taker_buy_pct": 0.5,
        "avg_trade_size": 10.0,
        "burst_detected": False,
        "burst_duration_seconds": 0.0,
        "burst_trade_pct": 0.0,
        "category": "Crypto",
        "series_prefix": "BTC",
        "hours_to_expiry": None,
        "markets_in_series": 0,
        "confidence": 0.5,
        "catalyst_type": "unknown",
    }
    defaults.update(overrides)
    return CatalystAnalysis(**defaults)


class TestRenderStructured:
    def test_returns_required_fields(self, renderer):
        analysis = _make_analysis()
        result = renderer.render_structured(analysis, "BTC Market")
        assert "headline" in result
        assert "narrative" in result
        assert "catalyst_type" in result
        assert "confidence" in result
        assert "signals" in result
        assert "source" in result
        assert result["source"] == "template"

    def test_whale_catalyst(self, renderer):
        analysis = _make_analysis(
            catalyst_type="whale",
            whale_trade_pct=0.75,
            confidence=0.6,
        )
        result = renderer.render_structured(analysis, "BTC 50K")
        assert "Large trades" in result["headline"]
        assert "75%" in result["narrative"]
        assert result["catalyst_type"] == "whale"

    def test_news_catalyst(self, renderer):
        analysis = _make_analysis(
            catalyst_type="news",
            burst_detected=True,
            burst_duration_seconds=30.0,
            burst_trade_pct=0.8,
            trades_per_minute=5.0,
        )
        result = renderer.render_structured(analysis, "Fed Rate")
        assert "burst" in result["headline"].lower() or "burst" in result["narrative"].lower()
        assert "news" in result["narrative"].lower() or "data release" in result["narrative"].lower()

    def test_momentum_catalyst(self, renderer):
        analysis = _make_analysis(
            catalyst_type="momentum",
            trade_count=20,
            taker_buy_pct=0.7,
            whale_trade_pct=0.1,
        )
        result = renderer.render_structured(analysis, "ETH Price")
        assert "pressure" in result["headline"].lower() or "pushed" in result["headline"].lower()
        assert "buy-side" in result["narrative"]

    def test_momentum_sell_side(self, renderer):
        analysis = _make_analysis(
            catalyst_type="momentum",
            direction="down",
            trade_count=20,
            taker_buy_pct=0.3,
            whale_trade_pct=0.1,
        )
        result = renderer.render_structured(analysis, "ETH Price")
        assert "sell-side" in result["narrative"]

    def test_pre_resolution_catalyst(self, renderer):
        analysis = _make_analysis(
            catalyst_type="pre_resolution",
            hours_to_expiry=2.5,
            magnitude_pct=0.15,
        )
        result = renderer.render_structured(analysis, "Election Market")
        assert "expiry" in result["headline"].lower() or "expiry" in result["narrative"].lower()
        assert "2.5h" in result["narrative"]

    def test_unknown_catalyst(self, renderer):
        analysis = _make_analysis(catalyst_type="unknown")
        result = renderer.render_structured(analysis, "Test Market")
        assert "Test Market" in result["headline"]
        assert result["catalyst_type"] == "unknown"

    def test_unknown_with_category(self, renderer):
        analysis = _make_analysis(catalyst_type="unknown", category="Sports")
        result = renderer.render_structured(analysis, "Game Score")
        assert "Sports" in result["narrative"]


class TestSignals:
    def test_collects_direction(self, renderer):
        analysis = _make_analysis(direction="up", magnitude_pct=0.05)
        result = renderer.render_structured(analysis, "Test")
        signals = result["signals"]
        assert any("up" in s for s in signals)

    def test_collects_trade_count(self, renderer):
        analysis = _make_analysis(trade_count=15)
        result = renderer.render_structured(analysis, "Test")
        assert any("15 trades" in s for s in result["signals"])

    def test_collects_whale_pct(self, renderer):
        analysis = _make_analysis(whale_trade_pct=0.6)
        result = renderer.render_structured(analysis, "Test")
        assert any("whale" in s.lower() for s in result["signals"])

    def test_collects_burst(self, renderer):
        analysis = _make_analysis(
            burst_detected=True,
            burst_trade_pct=0.8,
            burst_duration_seconds=20,
        )
        result = renderer.render_structured(analysis, "Test")
        assert any("burst" in s for s in result["signals"])

    def test_collects_expiry(self, renderer):
        analysis = _make_analysis(hours_to_expiry=3.0)
        result = renderer.render_structured(analysis, "Test")
        assert any("expiry" in s for s in result["signals"])

    def test_no_signals_for_empty(self, renderer):
        analysis = CatalystAnalysis(
            direction="unknown",
            magnitude_pct=0.0,
            trade_count=0,
        )
        result = renderer.render_structured(analysis, "Test")
        assert result["signals"] == []


class TestRenderPlainText:
    def test_returns_narrative_string(self, renderer):
        analysis = _make_analysis(catalyst_type="whale", whale_trade_pct=0.6)
        text = renderer.render(analysis, "Test Market")
        assert isinstance(text, str)
        assert len(text) > 20

    def test_matches_structured_narrative(self, renderer):
        analysis = _make_analysis()
        text = renderer.render(analysis, "Test Market")
        structured = renderer.render_structured(analysis, "Test Market")
        assert text == structured["narrative"]


class TestDirectionWords:
    def test_up_surged(self, renderer):
        analysis = _make_analysis(direction="up")
        result = renderer.render_structured(analysis, "Test")
        assert "surged" in result["headline"]

    def test_down_dropped(self, renderer):
        analysis = _make_analysis(direction="down")
        result = renderer.render_structured(analysis, "Test")
        assert "dropped" in result["headline"]

    def test_mixed_moved(self, renderer):
        analysis = _make_analysis(direction="mixed")
        result = renderer.render_structured(analysis, "Test")
        assert "moved" in result["headline"]
