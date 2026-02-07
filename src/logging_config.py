"""Logging configuration for Shopify-Everstox connector.

Provides structured logging with two output formats:
- Console: Rich-formatted colored output for development
- JSON: Structured JSON logs for production/log aggregation
"""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from rich.console import Console
from rich.logging import RichHandler

from src.config import LogFormat, get_settings


class JSONFormatter(logging.Formatter):
    """JSON log formatter for structured logging.

    Outputs each log record as a single JSON line with standardized fields
    suitable for log aggregation systems (e.g., ELK, Datadog, CloudWatch).
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON string.

        Args:
            record: The log record to format.

        Returns:
            JSON-formatted log string.
        """
        log_data: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add any extra fields passed via the extra parameter
        for key, value in record.__dict__.items():
            if key not in {
                "name",
                "msg",
                "args",
                "created",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "stack_info",
                "exc_info",
                "exc_text",
                "thread",
                "threadName",
                "taskName",
                "message",
            }:
                log_data[key] = value

        return json.dumps(log_data, default=str, ensure_ascii=False)


def setup_logging(
    log_level: str | None = None,
    log_format: LogFormat | None = None,
) -> logging.Logger:
    """Configure and return the application logger.

    Sets up logging based on configuration from environment variables or
    provided parameters. Supports two output formats:
    - CONSOLE: Rich-formatted output with colors for development
    - JSON: Structured JSON output for production environments

    Args:
        log_level: Override log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
            If None, uses LOG_LEVEL from environment/config.
        log_format: Override log format (CONSOLE or JSON).
            If None, uses LOG_FORMAT from environment/config.

    Returns:
        Configured logger instance for the application.

    Example:
        >>> logger = setup_logging()
        >>> logger.info("Application started")

        >>> # Override settings for testing
        >>> logger = setup_logging(log_level="DEBUG", log_format=LogFormat.CONSOLE)
    """
    settings = get_settings()

    # Use provided values or fall back to config
    level_str = log_level or settings.log_level
    format_type = log_format or settings.log_format

    # Get numeric log level
    level = getattr(logging, level_str.upper(), logging.INFO)

    # Get the root logger for our application
    logger = logging.getLogger("shopify_connector")
    logger.setLevel(level)

    # Clear any existing handlers to avoid duplicates
    logger.handlers.clear()

    # Prevent propagation to root logger to avoid duplicate logs
    logger.propagate = False

    handler: logging.Handler
    if format_type == LogFormat.JSON:
        # JSON format for production/log aggregation
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        handler.setLevel(level)
        logger.addHandler(handler)
    else:
        # Rich console format for development
        console = Console(stderr=True, force_terminal=True)
        handler = RichHandler(
            console=console,
            show_time=True,
            show_level=True,
            show_path=True,
            rich_tracebacks=True,
            tracebacks_show_locals=level <= logging.DEBUG,
            markup=True,
        )
        handler.setLevel(level)
        # Simpler format since Rich handles most formatting
        handler.setFormatter(logging.Formatter("%(message)s", datefmt="[%X]"))
        logger.addHandler(handler)

    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Get a logger instance for a specific module.

    Creates a child logger under the main application logger.
    If the main logger hasn't been set up yet, this will return
    a logger that inherits from the root logger.

    Args:
        name: Optional name for the logger. Typically use __name__.
            If None, returns the main application logger.

    Returns:
        Logger instance.

    Example:
        >>> # In a module file
        >>> from src.logging_config import get_logger
        >>> logger = get_logger(__name__)
        >>> logger.info("Processing order", extra={"order_id": "12345"})
    """
    base_logger = "shopify_connector"
    if name:
        return logging.getLogger(f"{base_logger}.{name}")
    return logging.getLogger(base_logger)
