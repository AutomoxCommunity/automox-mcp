"""Tests for idempotency cache infrastructure and write-tool integration."""

from __future__ import annotations

import time

from automox_mcp.utils.tooling import (
    _IDEMPOTENCY_CACHE,
    IdempotencyCache,
    check_idempotency,
    store_idempotency,
)

# ---------------------------------------------------------------------------
# IdempotencyCache unit tests
# ---------------------------------------------------------------------------


def test_cache_miss_returns_none():
    cache = IdempotencyCache()
    assert cache.get("req-1", "tool_a") is None


def test_cache_hit_returns_stored_response():
    cache = IdempotencyCache()
    resp = {"data": {"ok": True}}
    cache.put("req-1", "tool_a", resp)
    assert cache.get("req-1", "tool_a") == resp


def test_different_tool_name_is_separate_entry():
    cache = IdempotencyCache()
    cache.put("req-1", "tool_a", {"data": "a"})
    cache.put("req-1", "tool_b", {"data": "b"})
    assert cache.get("req-1", "tool_a") == {"data": "a"}
    assert cache.get("req-1", "tool_b") == {"data": "b"}


def test_ttl_expiry():
    cache = IdempotencyCache(ttl_seconds=0.05)
    cache.put("req-1", "tool_a", {"data": "x"})
    assert cache.get("req-1", "tool_a") is not None
    time.sleep(0.06)
    assert cache.get("req-1", "tool_a") is None


def test_max_entries_evicts_oldest():
    cache = IdempotencyCache(ttl_seconds=60)
    cache._MAX_ENTRIES = 3
    cache.put("r1", "t", {"v": 1})
    cache.put("r2", "t", {"v": 2})
    cache.put("r3", "t", {"v": 3})
    # Fourth entry should evict the oldest
    cache.put("r4", "t", {"v": 4})
    assert cache.get("r1", "t") is None
    assert cache.get("r4", "t") == {"v": 4}


def test_clear_empties_cache():
    cache = IdempotencyCache()
    cache.put("req-1", "tool_a", {"data": "x"})
    cache.clear()
    assert cache.get("req-1", "tool_a") is None


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


def test_check_idempotency_none_request_id_returns_none():
    assert check_idempotency(None, "any_tool") is None


def test_check_idempotency_empty_string_returns_none():
    assert check_idempotency("", "any_tool") is None


def test_store_idempotency_none_request_id_is_noop():
    store_idempotency(None, "any_tool", {"data": "x"})
    assert check_idempotency("anything", "any_tool") is None


def test_store_and_check_round_trip():
    store_idempotency("req-abc", "my_tool", {"result": 42})
    assert check_idempotency("req-abc", "my_tool") == {"result": 42}


def test_global_cache_is_reset_by_conftest():
    """The conftest fixture clears the global cache between tests."""
    # Store something — the next test should not see it
    _IDEMPOTENCY_CACHE.put("leak-test", "tool", {"leaked": True})
    assert _IDEMPOTENCY_CACHE.get("leak-test", "tool") is not None


def test_global_cache_is_clean():
    """Verify the fixture from the previous test cleaned up."""
    assert _IDEMPOTENCY_CACHE.get("leak-test", "tool") is None
