import json
import sys
from pathlib import Path

import pytest

from automox_mcp.client import AutomoxAPIError
from automox_mcp.utils.tooling import (
    RateLimiter,
    RateLimitError,
    as_tool_response,
    format_error,
)
from automox_mcp.workflows.policy import _normalize_status, _take


def test_as_tool_response_normalizes_metadata():
    original = {
        "data": {"ok": True},
        "metadata": {
            "current_page": 2,
            "total_pages": 5,
            "deprecated_endpoint": False,
        },
    }

    result = as_tool_response(original)

    assert result["data"]["ok"] is True
    assert result["metadata"]["current_page"] == 2
    assert result["metadata"]["deprecated_endpoint"] is False


def test_normalize_status_handles_variants():
    assert _normalize_status("Succeeded") == "success"
    assert _normalize_status("Partial_success") == "partial"
    assert _normalize_status("Failed") == "failed"
    assert _normalize_status("ErrorOccurred") == "failed"
    assert _normalize_status(None) == "unknown"


def test_take_limits_results():
    data = [1, 2, 3, 4]
    assert _take(data, 0) == []
    assert _take(data, 2) == [1, 2]


@pytest.mark.asyncio
async def test_rate_limiter_enforces_limit():
    limiter = RateLimiter(name="test limiter", max_calls=2, period_seconds=60)
    await limiter.acquire()
    await limiter.acquire()
    with pytest.raises(RateLimitError):
        await limiter.acquire()


def test_format_error_sanitizes_payload():
    exc = AutomoxAPIError(
        "Forbidden",
        status_code=403,
        payload={
            "message": "Access denied",
            "detail": "Insufficient permissions",
            "token": "should-not-appear",
        },
    )
    formatted = format_error(exc)
    assert "should-not-appear" not in formatted
    assert "Access denied" in formatted
    assert (
        json.loads(formatted.split("API Response:\n", 1)[1])["detail"] == "Insufficient permissions"
    )


def test_format_error_includes_errors_list():
    exc = AutomoxAPIError(
        "Bad Request",
        status_code=400,
        payload={
            "errors": [
                {"detail": "Zone assignment missing required uuid"},
                {"message": "Zone permissions must be specified"},
            ]
        },
    )
    formatted = format_error(exc)
    assert "Zone assignment missing required uuid" in formatted
    assert "Zone permissions must be specified" in formatted


def test_format_error_redacts_sensitive_values_on_fallback():
    exc = AutomoxAPIError(
        "Bad Request",
        status_code=400,
        payload={"api_token": "top-secret", "metadata": {"refreshKey": "123"}},
    )
    formatted = format_error(exc)
    assert "top-secret" not in formatted
    assert "***redacted***" in formatted


@pytest.mark.asyncio
async def test_create_server_registers_core_tools(monkeypatch):
    repo_root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(repo_root / "src"))
    monkeypatch.setenv("AUTOMOX_API_KEY", "test-key")
    monkeypatch.setenv("AUTOMOX_ACCOUNT_UUID", "test-account")
    monkeypatch.setenv("AUTOMOX_ORG_ID", "123")

    for name in list(sys.modules):
        if name == "automox_mcp" or name.startswith("automox_mcp."):
            sys.modules.pop(name, None)

    import automox_mcp

    server = automox_mcp.create_server()
    tools = await server.get_tools()
    tool_names = set(tools.keys())
    required = {"execute_policy_now", "execute_device_command", "audit_trail_user_activity"}
    assert required.issubset(tool_names)
