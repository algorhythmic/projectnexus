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
    kalshi_base_url: str = Field(
        default="https://trading-api.kalshi.com/trade-api/v2",
        description="Kalshi production API base URL",
    )
    kalshi_demo_base_url: str = Field(
        default="https://demo-api.kalshi.com/trade-api/v2",
        description="Kalshi demo/sandbox API base URL",
    )
    kalshi_use_demo: bool = Field(
        default=True,
        description="Use demo API by default for safety",
    )

    # Storage
    sqlite_path: str = Field(
        default="data/nexus.db", description="SQLite database file path"
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

    # Rate Limiting
    kalshi_reads_per_second: float = Field(
        default=15.0,
        description="Kalshi reads/sec (Basic tier limit is 20)",
    )

    # WebSocket
    kalshi_ws_url: str = Field(
        default="wss://trading-api.kalshi.com/trade-api/ws/v2",
        description="Kalshi production WebSocket URL",
    )
    kalshi_demo_ws_url: str = Field(
        default="wss://demo-api.kalshi.com/trade-api/ws/v2",
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


# Global settings instance
settings = Settings()
