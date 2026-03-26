"""Tests for structured JSON logging."""

from __future__ import annotations

import json
import logging
import os
from unittest.mock import patch

import pytest

from automox_mcp.utils.logging import JSONFormatter, configure_logging, get_log_format


class TestGetLogFormat:
    def test_default_text(self):
        with patch.dict(os.environ, {}, clear=True):
            assert get_log_format() == "text"

    def test_json(self):
        with patch.dict(os.environ, {"AUTOMOX_MCP_LOG_FORMAT": "json"}):
            assert get_log_format() == "json"

    def test_text_explicit(self):
        with patch.dict(os.environ, {"AUTOMOX_MCP_LOG_FORMAT": "text"}):
            assert get_log_format() == "text"

    def test_invalid_falls_back_to_text(self):
        with patch.dict(os.environ, {"AUTOMOX_MCP_LOG_FORMAT": "xml"}):
            assert get_log_format() == "text"

    def test_case_insensitive(self):
        with patch.dict(os.environ, {"AUTOMOX_MCP_LOG_FORMAT": "JSON"}):
            assert get_log_format() == "json"


class TestJSONFormatter:
    def _make_record(self, msg: str, level: int = logging.INFO) -> logging.LogRecord:
        return logging.LogRecord(
            name="automox_mcp.test",
            level=level,
            pathname="test.py",
            lineno=1,
            msg=msg,
            args=(),
            exc_info=None,
        )

    def test_produces_valid_json(self):
        formatter = JSONFormatter()
        record = self._make_record("simple message")
        output = formatter.format(record)
        parsed = json.loads(output)
        assert isinstance(parsed, dict)

    def test_has_required_keys(self):
        formatter = JSONFormatter()
        record = self._make_record("test event")
        parsed = json.loads(formatter.format(record))
        assert "timestamp" in parsed
        assert "level" in parsed
        assert "event" in parsed
        assert "logger" in parsed

    def test_timestamp_is_iso8601(self):
        formatter = JSONFormatter()
        record = self._make_record("test")
        parsed = json.loads(formatter.format(record))
        assert parsed["timestamp"].endswith("Z")

    def test_level_name(self):
        formatter = JSONFormatter()
        record = self._make_record("test", level=logging.WARNING)
        parsed = json.loads(formatter.format(record))
        assert parsed["level"] == "WARNING"

    def test_parses_tool_call_fields(self):
        formatter = JSONFormatter()
        msg = "tool_call tool=list_devices correlation_id=abc-123 status=ok latency=0.150s"
        record = self._make_record(msg)
        parsed = json.loads(formatter.format(record))
        assert parsed["tool_name"] == "list_devices"
        assert parsed["correlation_id"] == "abc-123"
        assert parsed["status"] == "ok"
        assert parsed["latency_ms"] == 150.0

    def test_error_status_parsed(self):
        formatter = JSONFormatter()
        msg = "tool_call tool=policy_catalog correlation_id=xyz status=error latency=0.500s"
        record = self._make_record(msg)
        parsed = json.loads(formatter.format(record))
        assert parsed["status"] == "error"
        assert parsed["latency_ms"] == 500.0

    def test_non_tool_message_no_extra_fields(self):
        formatter = JSONFormatter()
        record = self._make_record("just a regular log message")
        parsed = json.loads(formatter.format(record))
        assert "tool_name" not in parsed
        assert "correlation_id" not in parsed

    def test_exception_included(self):
        formatter = JSONFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys
            record = self._make_record("error occurred")
            record.exc_info = sys.exc_info()
        parsed = json.loads(formatter.format(record))
        assert "test error" in parsed["exception"]


class TestConfigureLogging:
    def test_json_mode_sets_handler(self):
        with patch.dict(os.environ, {"AUTOMOX_MCP_LOG_FORMAT": "json"}):
            configure_logging()
            root = logging.getLogger()
            assert any(
                isinstance(h.formatter, JSONFormatter) for h in root.handlers
            )
            # Clean up
            root.handlers.clear()

    def test_json_mode_idempotent(self):
        """Calling configure_logging twice should not add duplicate handlers."""
        with patch.dict(os.environ, {"AUTOMOX_MCP_LOG_FORMAT": "json"}):
            configure_logging()
            configure_logging()
            root = logging.getLogger()
            json_handlers = [
                h for h in root.handlers
                if isinstance(h.formatter, JSONFormatter)
            ]
            assert len(json_handlers) == 1
            root.handlers.clear()

    def test_text_mode(self):
        with patch.dict(os.environ, {"AUTOMOX_MCP_LOG_FORMAT": "text"}):
            configure_logging()
            root = logging.getLogger()
            # Should not have JSONFormatter
            assert not any(
                isinstance(h.formatter, JSONFormatter) for h in root.handlers
            )
            root.handlers.clear()
