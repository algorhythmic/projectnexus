"""Structured logging configuration for Nexus."""

import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import structlog
from rich.console import Console
from rich.logging import RichHandler

from nexus.core.config import settings


def configure_logging() -> None:
    """Configure structured logging for the application."""
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            (
                structlog.dev.ConsoleRenderer()
                if settings.debug
                else structlog.processors.JSONRenderer()
            ),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level)
        ),
        logger_factory=structlog.WriteLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    root = logging.getLogger()
    root.setLevel(getattr(logging, settings.log_level))
    # Clear any pre-existing handlers
    root.handlers.clear()
    if settings.debug:
        root.addHandler(
            RichHandler(
                console=Console(stderr=True),
                rich_tracebacks=True,
                markup=True,
            )
        )
    else:
        root.addHandler(logging.FileHandler(logs_dir / "nexus.log"))
        root.addHandler(logging.StreamHandler(sys.stdout))


def get_logger(name: Optional[str] = None) -> structlog.BoundLogger:
    """Get a structured logger instance."""
    if name is None:
        import inspect

        frame = inspect.currentframe()
        if frame and frame.f_back:
            name = frame.f_back.f_globals.get("__name__", "nexus")
        else:
            name = "nexus"
    return structlog.get_logger(name)


class LoggerMixin:
    """Mixin class to add structured logging to any class."""

    @property
    def logger(self) -> structlog.BoundLogger:
        """Get a logger instance bound to this class."""
        return get_logger(
            f"{self.__class__.__module__}.{self.__class__.__name__}"
        )

    def log_method_call(self, method_name: str, **kwargs: Any) -> None:
        """Log a method call with parameters."""
        self.logger.debug(
            "Method called",
            method=method_name,
            class_name=self.__class__.__name__,
            **kwargs,
        )

    def log_error(
        self, error: Exception, context: Optional[Dict[str, Any]] = None
    ) -> None:
        """Log an error with context."""
        self.logger.error(
            "Error occurred",
            error_type=type(error).__name__,
            error_message=str(error),
            class_name=self.__class__.__name__,
            **(context or {}),
        )


# Initialize logging when module is imported
configure_logging()
