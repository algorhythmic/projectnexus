"""Market intelligence — synthesized health scores from multi-source data.

This module combines trade flow, orderbook depth, and price momentum
into a single per-market health score that captures "why is this moving."
"""

from nexus.intelligence.health import MarketHealthTracker

__all__ = ["MarketHealthTracker"]
