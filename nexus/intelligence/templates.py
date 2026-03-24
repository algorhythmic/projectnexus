"""Template-based alert rendering for anomaly catalyst analysis.

Transforms a CatalystAnalysis into human-readable narratives without
an LLM.  This serves as the control condition for Hypothesis C and as
a zero-cost fallback when the LLM layer is disabled.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from nexus.intelligence.narrative import CatalystAnalysis


class TemplateRenderer:
    """Renders CatalystAnalysis into structured alert text."""

    def render(self, analysis: CatalystAnalysis, market_title: str) -> str:
        """Produce a 2-4 sentence plain-text summary."""
        result = self.render_structured(analysis, market_title)
        return result["narrative"]

    def render_structured(
        self, analysis: CatalystAnalysis, market_title: str
    ) -> Dict[str, Any]:
        """Produce a structured alert object with headline, narrative, and signals."""
        direction_word = {
            "up": "surged",
            "down": "dropped",
            "mixed": "moved",
            "flat": "held steady",
        }.get(analysis.direction, "moved")

        magnitude_str = f"{analysis.magnitude_pct:.1%}"

        headline = self._make_headline(
            analysis, market_title, direction_word, magnitude_str
        )
        narrative = self._make_narrative(
            analysis, market_title, direction_word, magnitude_str
        )
        signals = self._collect_signals(analysis)

        return {
            "headline": headline,
            "narrative": narrative,
            "catalyst_type": analysis.catalyst_type,
            "confidence": round(analysis.confidence, 2),
            "signals": signals,
            "source": "template",
        }

    def _make_headline(
        self,
        a: CatalystAnalysis,
        title: str,
        direction_word: str,
        magnitude: str,
    ) -> str:
        """One-line headline summarizing the anomaly."""
        templates = {
            "whale": f"Large trades drove {title} {direction_word} {magnitude}",
            "news": f"Activity burst hit {title} — {direction_word} {magnitude}",
            "momentum": f"Sustained pressure pushed {title} {direction_word} {magnitude}",
            "pre_resolution": f"Pre-expiry move on {title} — {direction_word} {magnitude}",
            "unknown": f"{title} {direction_word} {magnitude}",
        }
        return templates.get(a.catalyst_type, templates["unknown"])

    def _make_narrative(
        self,
        a: CatalystAnalysis,
        title: str,
        direction_word: str,
        magnitude: str,
    ) -> str:
        """2-4 sentence narrative explaining the anomaly."""
        price_ctx = ""
        if a.price_from is not None and a.price_to is not None:
            price_ctx = f" from {a.price_from:.0%} to {a.price_to:.0%}"

        if a.catalyst_type == "whale":
            return (
                f"{title} {direction_word} {magnitude}{price_ctx}. "
                f"{a.whale_trade_pct:.0%} of volume came from large trades "
                f"(over $500 each) across {a.trade_count} trades. "
                f"This pattern suggests a few large participants drove the move "
                f"rather than broad market sentiment."
            )

        if a.catalyst_type == "news":
            burst_info = ""
            if a.burst_duration_seconds > 0:
                burst_info = (
                    f", concentrated in a {a.burst_duration_seconds:.0f}s burst"
                )
            return (
                f"{title} {direction_word} {magnitude}{price_ctx} "
                f"on {a.trades_per_minute:.1f} trades/min{burst_info}. "
                f"The concentrated activity pattern is consistent with "
                f"a news-driven reaction or data release."
            )

        if a.catalyst_type == "momentum":
            buy_sell = (
                "buy-side" if a.taker_buy_pct > 0.5 else "sell-side"
            )
            return (
                f"{title} {direction_word} {magnitude}{price_ctx} "
                f"over {a.trade_count} trades. "
                f"The move was {buy_sell}-driven "
                f"({a.taker_buy_pct:.0%} taker buys) with no whale "
                f"dominance, suggesting broad directional conviction."
            )

        if a.catalyst_type == "pre_resolution":
            expiry_str = (
                f"{a.hours_to_expiry:.1f}h" if a.hours_to_expiry else "soon"
            )
            return (
                f"{title} {direction_word} {magnitude}{price_ctx} "
                f"with expiry in {expiry_str}. "
                f"Pre-resolution moves of this magnitude often reflect "
                f"converging expectations as the outcome approaches."
            )

        # "unknown" — generic
        parts = [f"{title} {direction_word} {magnitude}{price_ctx}."]
        if a.trade_count > 0:
            parts.append(
                f" {a.trade_count} trades at "
                f"{a.trades_per_minute:.1f}/min."
            )
        if a.category:
            parts.append(f" Category: {a.category}.")
        return "".join(parts)

    @staticmethod
    def _collect_signals(a: CatalystAnalysis) -> List[str]:
        """Key evidence points as short strings."""
        signals: List[str] = []
        if a.magnitude_pct > 0:
            signals.append(f"{a.direction} {a.magnitude_pct:.1%}")
        if a.trade_count > 0:
            signals.append(f"{a.trade_count} trades")
        if a.whale_trade_pct > 0.1:
            signals.append(f"{a.whale_trade_pct:.0%} whale volume")
        if a.burst_detected:
            signals.append(
                f"burst: {a.burst_trade_pct:.0%} of trades in "
                f"{a.burst_duration_seconds:.0f}s"
            )
        if a.taker_buy_pct > 0 and a.trade_count > 0:
            signals.append(f"{a.taker_buy_pct:.0%} buy-side")
        if a.hours_to_expiry is not None and a.hours_to_expiry < 12:
            signals.append(f"{a.hours_to_expiry:.1f}h to expiry")
        return signals
