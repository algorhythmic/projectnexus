"""Configuration management for Nexus."""

from typing import List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from nexus.core.types import WindowConfig


class Settings(BaseSettings):
    """Application settings with environment variable support."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "Nexus"
    debug: bool = False
    log_level: str = "INFO"

    # Kalshi API
    kalshi_api_key: str = Field(
        default="", description="Kalshi API Key ID"
    )
    kalshi_private_key_path: str = Field(
        default="", description="Path to RSA private key PEM file"
    )
    kalshi_private_key_pem: str = Field(
        default="",
        description="RSA private key PEM content (alternative to file path, for containerized deployments)",
    )
    kalshi_base_url: str = Field(
        default="https://api.elections.kalshi.com/trade-api/v2",
        description="Kalshi production API base URL",
    )
    kalshi_demo_base_url: str = Field(
        default="https://demo-api.kalshi.co/trade-api/v2",
        description="Kalshi demo/sandbox API base URL",
    )
    kalshi_use_demo: bool = Field(
        default=True,
        description="Use demo API by default for safety",
    )

    # Storage
    store_backend: str = Field(
        default="sqlite",
        description="Storage backend: 'sqlite' or 'postgres'",
    )
    sqlite_path: str = Field(
        default="data/nexus.db", description="SQLite database file path"
    )
    postgres_dsn: str = Field(
        default="",
        description="PostgreSQL connection string (e.g. postgresql://user:pass@host/db)",
    )
    postgres_pool_min: int = Field(
        default=2, description="Minimum connections in asyncpg pool"
    )
    postgres_pool_max: int = Field(
        default=10, description="Maximum connections in asyncpg pool"
    )

    # Polling
    discovery_interval_seconds: int = Field(
        default=60, description="REST polling interval in seconds"
    )
    max_concurrent_requests: int = Field(
        default=10, description="Max concurrent API requests"
    )
    request_timeout: int = Field(
        default=30, description="Request timeout in seconds"
    )

    kalshi_discovery_max_pages: int = Field(
        default=5,
        description="Max pages to fetch during Kalshi discovery (0 = unlimited, 200 markets/page)",
    )
    discovery_staleness_hours: int = Field(
        default=2,
        description="Deactivate markets not seen in discovery for this many hours (safety net)",
    )

    # Rate Limiting
    kalshi_reads_per_second: float = Field(
        default=15.0,
        description="Kalshi reads/sec (Basic tier limit is 20)",
    )

    # WebSocket
    kalshi_ws_url: str = Field(
        default="wss://api.elections.kalshi.com/trade-api/ws/v2",
        description="Kalshi production WebSocket URL",
    )
    kalshi_demo_ws_url: str = Field(
        default="wss://demo-api.kalshi.co/trade-api/ws/v2",
        description="Kalshi demo WebSocket URL",
    )
    ws_reconnect_delay: float = Field(
        default=1.0, description="Initial reconnect delay in seconds"
    )
    ws_reconnect_max_delay: float = Field(
        default=60.0, description="Max reconnect delay (backoff cap)"
    )
    ws_ping_interval: int = Field(
        default=10, description="Seconds between WebSocket pings"
    )
    ws_max_subscriptions: int = Field(
        default=200, description="Max tickers per WebSocket connection"
    )

    # Polymarket API
    polymarket_base_url: str = Field(
        default="https://gamma-api.polymarket.com",
        description="Polymarket Gamma API base URL",
    )
    polymarket_ws_url: str = Field(
        default="wss://ws-subscriptions-clob.polymarket.com/ws/market",
        description="Polymarket CLOB WebSocket URL for market data",
    )
    polymarket_reads_per_second: float = Field(
        default=25.0,
        description="Polymarket reads/sec (API limit is 300/10s)",
    )
    polymarket_ws_ping_interval: int = Field(
        default=10,
        description="Seconds between PING heartbeats to Polymarket WebSocket",
    )
    polymarket_discovery_page_size: int = Field(
        default=100,
        description="Number of markets per page in Polymarket discovery",
    )
    polymarket_enabled: bool = Field(
        default=False,
        description="Enable Polymarket adapter",
    )

    # Event Bus
    event_queue_max_size: int = Field(
        default=10_000, description="Bounded asyncio.Queue max size"
    )
    event_batch_size: int = Field(
        default=100, description="Events per batch drain"
    )
    event_batch_timeout: float = Field(
        default=1.0, description="Max seconds before flushing partial batch"
    )

    # Monitoring
    health_report_interval_seconds: int = Field(
        default=60, description="Seconds between health report log entries"
    )

    # LLM / Clustering
    anthropic_api_key: str = Field(
        default="", description="Anthropic API key for Claude"
    )
    clustering_model: str = Field(
        default="claude-sonnet-4-20250514",
        description="Claude model for clustering",
    )
    clustering_temperature: float = Field(
        default=0.1, description="LLM temperature (low = deterministic)"
    )
    clustering_max_tokens: int = Field(
        default=4096, description="Max output tokens per LLM call"
    )
    clustering_batch_size: int = Field(
        default=30, description="Markets per LLM batch call"
    )
    clustering_min_confidence: float = Field(
        default=0.6, description="Minimum confidence for cluster assignment"
    )

    # Anomaly Detection
    anomaly_detection_interval_seconds: int = Field(
        default=300, description="Seconds between detection cycles"
    )
    detection_startup_delay_seconds: int = Field(
        default=120,
        description="Seconds to wait before starting anomaly detection (allows events to accumulate)",
    )
    anomaly_windows: str = Field(
        default="5,15,60,1440",
        description="Comma-separated window sizes in minutes",
    )
    anomaly_price_change_threshold: float = Field(
        default=0.10, description="Price change threshold (0.10 = 10%)"
    )
    anomaly_volume_spike_multiplier: float = Field(
        default=3.0, description="Volume spike multiplier over baseline"
    )
    anomaly_zscore_threshold: float = Field(
        default=2.5, description="Z-score threshold for anomaly"
    )
    anomaly_baseline_hours: int = Field(
        default=24, description="Lookback hours for Z-score baseline"
    )
    anomaly_expiry_hours: int = Field(
        default=24, description="Auto-expire anomalies older than this"
    )

    # Cluster Correlation (Milestone 2.3)
    cluster_anomaly_min_markets: int = Field(
        default=2,
        description="Min markets in cluster that must be anomalous to trigger cluster alert",
    )
    cluster_anomaly_window_minutes: int = Field(
        default=60,
        description="Time window (minutes) to check for concurrent anomalies",
    )

    # Cross-Platform Correlation (Milestone 3.3)
    cross_platform_enabled: bool = Field(
        default=True,
        description="Enable cross-platform link detection and correlation",
    )
    cross_platform_window_minutes: int = Field(
        default=60,
        description="Time window (minutes) to check for cross-platform anomaly pairs",
    )

    # Data Retention (Milestone 3.3)
    retention_days: int = Field(
        default=0,
        description="Delete events older than N days (0 = keep forever)",
    )

    # Convex Sync (Phase 4)
    convex_deployment_url: str = Field(
        default="",
        description="Convex deployment URL (e.g. https://your-deployment.convex.cloud)",
    )
    convex_deploy_key: str = Field(
        default="",
        description="Convex deploy key for server-to-server auth",
    )
    sync_market_interval_seconds: int = Field(
        default=30,
        description="Sync market state to Convex every N seconds",
    )
    sync_summary_interval_seconds: int = Field(
        default=1800,
        description="Sync market summaries to Convex every N seconds",
    )
    sync_topics_interval_seconds: int = Field(
        default=300,
        description="Sync trending topics to Convex every N seconds",
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in valid_levels:
            raise ValueError(f"Log level must be one of {valid_levels}")
        return v.upper()

    @property
    def effective_kalshi_url(self) -> str:
        """Get the Kalshi API URL based on demo mode setting."""
        if self.kalshi_use_demo:
            return self.kalshi_demo_base_url
        return self.kalshi_base_url

    @property
    def anomaly_window_configs(self) -> List[WindowConfig]:
        """Parse anomaly_windows string into WindowConfig objects."""
        return [
            WindowConfig(
                window_minutes=int(w.strip()),
                price_change_threshold=self.anomaly_price_change_threshold,
                volume_spike_multiplier=self.anomaly_volume_spike_multiplier,
                zscore_threshold=self.anomaly_zscore_threshold,
            )
            for w in self.anomaly_windows.split(",")
            if w.strip()
        ]

    @property
    def effective_kalshi_ws_url(self) -> str:
        """Get the Kalshi WebSocket URL based on demo mode setting."""
        if self.kalshi_use_demo:
            return self.kalshi_demo_ws_url
        return self.kalshi_ws_url

    _SECRET_FIELDS = frozenset({
        "kalshi_api_key", "kalshi_private_key_pem", "kalshi_private_key_path",
        "postgres_dsn", "convex_deploy_key", "anthropic_api_key",
    })

    def __repr__(self) -> str:
        """Redact secrets from repr to prevent leaking in tracebacks/logs."""
        fields = []
        for name in self.model_fields:
            value = getattr(self, name)
            if name in self._SECRET_FIELDS and value:
                fields.append(f"{name}='***'")
            else:
                fields.append(f"{name}={value!r}")
        return f"Settings({', '.join(fields)})"

    __str__ = __repr__


# Global settings instance
settings = Settings()
