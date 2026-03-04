"""Configuration management for Nexus."""

from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    def effective_kalshi_ws_url(self) -> str:
        """Get the Kalshi WebSocket URL based on demo mode setting."""
        if self.kalshi_use_demo:
            return self.kalshi_demo_ws_url
        return self.kalshi_ws_url


# Global settings instance
settings = Settings()
