"""Tests for correlation ID middleware."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from automox_mcp.middleware import (
    CorrelationMiddleware,
    _correlation_id_var,
    get_correlation_id,
)
from automox_mcp.utils.tooling import as_tool_response


def test_get_correlation_id_returns_none_by_default():
    assert get_correlation_id() is None


def test_get_correlation_id_reads_context_var():
    token = _correlation_id_var.set("test-id-123")
    try:
        assert get_correlation_id() == "test-id-123"
    finally:
        _correlation_id_var.reset(token)


@pytest.mark.asyncio
async def test_middleware_sets_and_resets_correlation_id():
    mw = CorrelationMiddleware()

    captured_id: str | None = None

    async def fake_call_next(context: Any) -> str:
        nonlocal captured_id
        captured_id = get_correlation_id()
        return "ok"

    class FakeMessage:
        name = "test_tool"

    class FakeContext:
        message = FakeMessage()

    await mw.on_call_tool(FakeContext(), fake_call_next)

    # Correlation ID was set during call
    assert captured_id is not None
    assert len(captured_id) == 36  # UUID4 format
    uuid.UUID(captured_id)  # Validates format

    # Reset after call
    assert get_correlation_id() is None


@pytest.mark.asyncio
async def test_middleware_resets_on_exception():
    mw = CorrelationMiddleware()

    async def failing_call_next(context: Any) -> str:
        raise RuntimeError("boom")

    class FakeMessage:
        name = "failing_tool"

    class FakeContext:
        message = FakeMessage()

    with pytest.raises(RuntimeError, match="boom"):
        await mw.on_call_tool(FakeContext(), failing_call_next)

    # Still reset after failure
    assert get_correlation_id() is None


@pytest.mark.asyncio
async def test_middleware_logs_success(caplog):
    import logging

    mw = CorrelationMiddleware()

    async def fake_call_next(context: Any) -> str:
        return "ok"

    class FakeMessage:
        name = "my_tool"

    class FakeContext:
        message = FakeMessage()

    with caplog.at_level(logging.INFO, logger="automox_mcp.middleware"):
        await mw.on_call_tool(FakeContext(), fake_call_next)

    log_messages = [r.message for r in caplog.records]
    assert any("tool=my_tool" in m and "status=ok" in m for m in log_messages)


@pytest.mark.asyncio
async def test_middleware_logs_failure(caplog):
    import logging

    mw = CorrelationMiddleware()

    async def failing_call_next(context: Any) -> str:
        raise ValueError("bad input")

    class FakeMessage:
        name = "bad_tool"

    class FakeContext:
        message = FakeMessage()

    with caplog.at_level(logging.INFO, logger="automox_mcp.middleware"):
        with pytest.raises(ValueError):
            await mw.on_call_tool(FakeContext(), failing_call_next)

    log_messages = [r.message for r in caplog.records]
    assert any("tool=bad_tool" in m and "status=error" in m for m in log_messages)


def test_as_tool_response_includes_correlation_id():
    token = _correlation_id_var.set("resp-id-456")
    try:
        result = as_tool_response({"data": {"x": 1}, "metadata": {}})
        assert result["metadata"]["correlation_id"] == "resp-id-456"
    finally:
        _correlation_id_var.reset(token)


def test_as_tool_response_omits_correlation_id_when_none():
    result = as_tool_response({"data": {"x": 1}, "metadata": {}})
    assert result["metadata"].get("correlation_id") is None
