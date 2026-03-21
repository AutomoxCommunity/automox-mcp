"""Tests for src/automox_mcp/utils/tooling.py — covering previously uncovered branches."""

from __future__ import annotations

import pytest

from automox_mcp.client import AutomoxAPIError
from automox_mcp.utils.tooling import (
    RateLimiter,
    RateLimitError,
    _has_content,
    _sanitize_errors,
    as_tool_response,
    format_error,
    get_enabled_modules,
)

# ---------------------------------------------------------------------------
# get_enabled_modules with a set env var (line 33)
# ---------------------------------------------------------------------------


def test_get_enabled_modules_returns_none_when_unset(monkeypatch):
    monkeypatch.delenv("AUTOMOX_MCP_MODULES", raising=False)
    assert get_enabled_modules() is None


def test_get_enabled_modules_returns_set_of_names(monkeypatch):
    monkeypatch.setenv("AUTOMOX_MCP_MODULES", "devices, Policies , webhooks")
    result = get_enabled_modules()
    assert result == {"devices", "policies", "webhooks"}


def test_get_enabled_modules_ignores_blank_entries(monkeypatch):
    monkeypatch.setenv("AUTOMOX_MCP_MODULES", "devices,,events,")
    result = get_enabled_modules()
    assert result == {"devices", "events"}


# ---------------------------------------------------------------------------
# RateLimiter validation errors (lines 45, 47)
# ---------------------------------------------------------------------------


def test_rate_limiter_rejects_zero_max_calls():
    with pytest.raises(ValueError, match="max_calls must be greater than zero"):
        RateLimiter(name="test", max_calls=0, period_seconds=60)


def test_rate_limiter_rejects_negative_max_calls():
    with pytest.raises(ValueError, match="max_calls must be greater than zero"):
        RateLimiter(name="test", max_calls=-1, period_seconds=60)


def test_rate_limiter_rejects_zero_period():
    with pytest.raises(ValueError, match="period_seconds must be greater than zero"):
        RateLimiter(name="test", max_calls=10, period_seconds=0)


def test_rate_limiter_rejects_negative_period():
    with pytest.raises(ValueError, match="period_seconds must be greater than zero"):
        RateLimiter(name="test", max_calls=10, period_seconds=-5.0)


# ---------------------------------------------------------------------------
# Rate limiter window expiration (line 59) — old timestamps are pruned
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limiter_prunes_expired_timestamps():
    """Timestamps outside the sliding window must be discarded so new calls succeed."""
    limiter = RateLimiter(name="expiry-test", max_calls=2, period_seconds=0.05)

    await limiter.acquire()
    await limiter.acquire()

    # Both slots are full; a third call should fail immediately.
    with pytest.raises(RateLimitError):
        await limiter.acquire()

    # Wait long enough for the window to roll over.
    import asyncio

    await asyncio.sleep(0.1)

    # The old timestamps are now outside the window and must be pruned,
    # allowing two fresh calls.
    await limiter.acquire()
    await limiter.acquire()


# ---------------------------------------------------------------------------
# _has_content helper branches (lines 84-86)
# ---------------------------------------------------------------------------


def test_has_content_none_returns_false():
    assert _has_content(None) is False


def test_has_content_blank_string_returns_false():
    assert _has_content("   ") is False


def test_has_content_non_blank_string_returns_true():
    assert _has_content("hello") is True


def test_has_content_empty_list_returns_false():
    assert _has_content([]) is False


def test_has_content_non_empty_list_returns_true():
    assert _has_content([1]) is True


def test_has_content_empty_dict_returns_false():
    assert _has_content({}) is False


def test_has_content_non_empty_dict_returns_true():
    assert _has_content({"a": 1}) is True


def test_has_content_integer_returns_true():
    # Falls through to the final `return True` branch (line 86)
    assert _has_content(42) is True


def test_has_content_zero_returns_true():
    # 0 is not None and not a string/mapping/sequence, so it is truthy in this context
    assert _has_content(0) is True


# ---------------------------------------------------------------------------
# _sanitize_errors helper branches (lines 91-112)
# ---------------------------------------------------------------------------


def test_sanitize_errors_mapping_keeps_allowed_keys():
    result = _sanitize_errors({"message": "bad request", "token": "secret", "code": "ERR"})
    assert result == {"message": "bad request", "code": "ERR"}
    assert "token" not in (result or {})


def test_sanitize_errors_mapping_returns_none_when_all_filtered():
    # All keys are disallowed — result should be None
    result = _sanitize_errors({"token": "secret", "password": "123"})
    assert result is None


def test_sanitize_errors_mapping_filters_empty_values():
    # Allowed key but empty string value — should be excluded
    result = _sanitize_errors({"message": "   ", "code": "ERR"})
    assert result == {"code": "ERR"}


def test_sanitize_errors_list_of_mappings(lines=None):
    """Lines 97-107: list input with Mapping items."""
    errors = [
        {"detail": "field required", "token": "leak"},
        {"message": "too short"},
    ]
    result = _sanitize_errors(errors)
    assert result == [{"detail": "field required"}, {"message": "too short"}]


def test_sanitize_errors_list_items_with_no_allowed_keys_are_dropped():
    """Mapping items with only disallowed keys are dropped from the list."""
    errors = [
        {"token": "leak"},
        {"message": "keep me"},
    ]
    result = _sanitize_errors(errors)
    assert result == [{"message": "keep me"}]


def test_sanitize_errors_list_of_primitives(lines=None):
    """Line 108-109: non-Mapping list items that have content are kept."""
    result = _sanitize_errors(["error one", "error two"])
    assert result == ["error one", "error two"]


def test_sanitize_errors_list_of_primitives_empty_strings_dropped():
    result = _sanitize_errors(["", "  ", "real error"])
    assert result == ["real error"]


def test_sanitize_errors_empty_list_returns_none():
    """An empty list (or all-filtered list) should return None."""
    result = _sanitize_errors([])
    assert result is None


def test_sanitize_errors_list_all_filtered_returns_none():
    result = _sanitize_errors([{"token": "x"}])
    assert result is None


def test_sanitize_errors_scalar_with_content(lines=None):
    """Line 111-112: non-mapping, non-sequence scalar that has content."""
    result = _sanitize_errors(42)
    assert result == 42


def test_sanitize_errors_scalar_none_value():
    result = _sanitize_errors(None)
    assert result is None


# ---------------------------------------------------------------------------
# format_error TypeError fallback on json.dumps (lines 152-153)
# ---------------------------------------------------------------------------


def test_format_error_falls_back_to_repr_on_type_error(monkeypatch):
    """If json.dumps raises TypeError, format_error falls back to repr()."""
    import json as json_mod

    import automox_mcp.utils.tooling as tooling_mod

    original_dumps = json_mod.dumps

    def bad_dumps(obj, **kwargs):
        if obj:  # only fail on non-empty payloads
            raise TypeError("not serializable")
        return original_dumps(obj, **kwargs)

    monkeypatch.setattr(tooling_mod.json, "dumps", bad_dumps)

    exc = AutomoxAPIError("oops", status_code=500, payload={"message": "oops"})
    result = format_error(exc)
    # repr() output is used instead of JSON
    assert "API Response:" in result
    assert "oops" in result


# ---------------------------------------------------------------------------
# as_tool_response with non-Mapping metadata (line 162)
# ---------------------------------------------------------------------------


def test_as_tool_response_with_non_mapping_metadata():
    """When metadata is not a Mapping, it should be treated as empty."""
    result = as_tool_response({"data": [1, 2, 3], "metadata": "not-a-dict"})
    assert result["data"] == [1, 2, 3]
    # PaginationMetadata defaults should all be None / False
    assert result["metadata"]["current_page"] is None
    assert result["metadata"]["deprecated_endpoint"] is False


def test_as_tool_response_with_missing_metadata():
    """metadata key absent from result — treated as empty Mapping."""
    result = as_tool_response({"data": {"ok": True}})
    assert result["data"] == {"ok": True}
    assert result["metadata"]["total_count"] is None


def test_as_tool_response_with_none_metadata():
    """metadata=None should be treated as empty Mapping."""
    result = as_tool_response({"data": None, "metadata": None})
    assert result["data"] is None
    assert result["metadata"]["current_page"] is None
