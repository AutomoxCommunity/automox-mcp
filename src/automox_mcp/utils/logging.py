"""Structured JSON logging formatter for SIEM integration.

Enabled via ``AUTOMOX_MCP_LOG_FORMAT=json``.  Default is ``text``
(standard Python logging format).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any


def get_log_format() -> str:
    """Return the configured log format: 'json' or 'text'."""
    value = os.environ.get("AUTOMOX_MCP_LOG_FORMAT", "text").strip().lower()
    return value if value in {"json", "text"} else "text"


class JSONFormatter(logging.Formatter):
    """Emit one JSON object per log line for SIEM consumption."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC)
            .isoformat()
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }

        # Extract structured fields from the log message if available.
        # The correlation middleware logs: "tool_call tool=X correlation_id=Y ..."
        msg = entry["event"]
        if msg.startswith("tool_call "):
            parts = msg.split()
            for part in parts[1:]:
                if "=" in part:
                    key, _, value = part.partition("=")
                    if key == "tool":
                        entry["tool_name"] = value
                    elif key == "correlation_id":
                        entry["correlation_id"] = value
                    elif key == "status":
                        entry["status"] = value
                    elif key == "latency":
                        try:
                            entry["latency_ms"] = round(float(value.rstrip("s")) * 1000, 1)
                        except (ValueError, TypeError):
                            entry["latency_raw"] = value

        if record.exc_info and record.exc_info[1]:
            entry["exception"] = str(record.exc_info[1])

        return json.dumps(entry, default=str)


def configure_logging() -> None:
    """Set up the root logger based on AUTOMOX_MCP_LOG_FORMAT."""
    fmt = get_log_format()
    root = logging.getLogger()

    if fmt == "json":
        # Check if a JSON handler is already configured to avoid duplicates
        already_configured = any(isinstance(h.formatter, JSONFormatter) for h in root.handlers)
        if not already_configured:
            handler = logging.StreamHandler()
            handler.setFormatter(JSONFormatter())
            root.addHandler(handler)
        if root.level == logging.NOTSET:
            root.setLevel(logging.INFO)
    else:
        logging.basicConfig(level=logging.INFO)


__all__ = ["JSONFormatter", "configure_logging", "get_log_format"]
