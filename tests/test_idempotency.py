"""Tests for idempotency cache infrastructure and write-tool integration."""

from __future__ import annotations

import asyncio

import pytest

from automox_mcp.utils.tooling import (
    _IDEMPOTENCY_CACHE,
    IdempotencyCache,
    check_idempotency,
    release_idempotency,
    store_idempotency,
)

# ---------------------------------------------------------------------------
# IdempotencyCache unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_miss_returns_none():
    cache = IdempotencyCache()
    assert await cache.get("req-1", "tool_a") is None


@pytest.mark.asyncio
async def test_cache_hit_returns_stored_response():
    cache = IdempotencyCache()
    resp = {"data": {"ok": True}}
    await cache.put("req-1", "tool_a", resp)
    assert await cache.get("req-1", "tool_a") == resp


@pytest.mark.asyncio
async def test_different_tool_name_is_separate_entry():
    cache = IdempotencyCache()
    await cache.put("req-1", "tool_a", {"data": "a"})
    await cache.put("req-1", "tool_b", {"data": "b"})
    assert await cache.get("req-1", "tool_a") == {"data": "a"}
    assert await cache.get("req-1", "tool_b") == {"data": "b"}


@pytest.mark.asyncio
async def test_ttl_expiry():
    cache = IdempotencyCache(ttl_seconds=0.05)
    await cache.put("req-1", "tool_a", {"data": "x"})
    assert await cache.get("req-1", "tool_a") is not None
    await asyncio.sleep(0.15)  # generous margin for CI
    assert await cache.get("req-1", "tool_a") is None


@pytest.mark.asyncio
async def test_max_entries_evicts_oldest():
    cache = IdempotencyCache(ttl_seconds=60)
    cache._MAX_ENTRIES = 3
    await cache.put("r1", "t", {"v": 1})
    await cache.put("r2", "t", {"v": 2})
    await cache.put("r3", "t", {"v": 3})
    # Fourth entry should evict the oldest
    await cache.put("r4", "t", {"v": 4})
    assert await cache.get("r1", "t") is None
    assert await cache.get("r4", "t") == {"v": 4}


@pytest.mark.asyncio
async def test_clear_empties_cache():
    cache = IdempotencyCache()
    await cache.put("req-1", "tool_a", {"data": "x"})
    cache.clear()
    assert await cache.get("req-1", "tool_a") is None


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_idempotency_none_request_id_returns_none():
    assert await check_idempotency(None, "any_tool") is None


@pytest.mark.asyncio
async def test_check_idempotency_empty_string_returns_none():
    assert await check_idempotency("", "any_tool") is None


@pytest.mark.asyncio
async def test_store_idempotency_none_request_id_is_noop():
    await store_idempotency(None, "any_tool", {"data": "x"})
    assert await check_idempotency("anything", "any_tool") is None


@pytest.mark.asyncio
async def test_store_and_check_round_trip():
    await store_idempotency("req-abc", "my_tool", {"result": 42})
    assert await check_idempotency("req-abc", "my_tool") == {"result": 42}


@pytest.mark.asyncio
async def test_global_cache_is_reset_by_conftest():
    """The conftest fixture clears the global cache between tests."""
    # Store something -- the next test should not see it
    await _IDEMPOTENCY_CACHE.put("leak-test", "tool", {"leaked": True})
    assert await _IDEMPOTENCY_CACHE.get("leak-test", "tool") is not None


@pytest.mark.asyncio
async def test_global_cache_is_clean():
    """Verify the fixture from the previous test cleaned up."""
    assert await _IDEMPOTENCY_CACHE.get("leak-test", "tool") is None


# ---------------------------------------------------------------------------
# release_idempotency: failure-path sentinel cleanup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_release_clears_inflight_sentinel_so_retry_can_proceed():
    """A reserved slot must be released on the failure path, otherwise every
    retry with the same request_id is shadowed by the in-flight sentinel for
    the full TTL.
    """
    # Reserve the slot (simulates check_idempotency entering the body).
    cached = await check_idempotency("req-fail", "tool_x")
    assert cached is None  # fresh reservation

    # Simulate workflow failure: release the sentinel before raising.
    await release_idempotency("req-fail", "tool_x")

    # Next retry must see a clean slate, not the duplicate marker.
    cached_after = await check_idempotency("req-fail", "tool_x")
    assert cached_after is None


@pytest.mark.asyncio
async def test_release_does_not_clobber_completed_entry():
    """If a parallel worker already stored a real response, release() must not
    erase it — that would defeat the idempotency guarantee.
    """
    await check_idempotency("req-done", "tool_x")  # reserve
    await store_idempotency("req-done", "tool_x", {"data": {"ok": True}})

    await release_idempotency("req-done", "tool_x")

    # The stored response must still be returned to subsequent retries.
    cached = await check_idempotency("req-done", "tool_x")
    assert cached == {"data": {"ok": True}}


@pytest.mark.asyncio
async def test_release_with_none_request_id_is_noop():
    # Mirrors store_idempotency's None-tolerance — callers shouldn't have to
    # branch on whether request_id was supplied.
    await release_idempotency(None, "tool_x")
    await release_idempotency("", "tool_x")
