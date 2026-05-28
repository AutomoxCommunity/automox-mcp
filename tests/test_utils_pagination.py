"""Tests for the parallel_paginate helper (issue #69).

Covers the acceptance criteria from the issue:
  - single-page response (no parallel batches spun up)
  - exact-multiple-of-page-size last page (off-by-one boundary)
  - short-page termination mid-batch (discard later pages in same batch)
  - on_page early stop (limit-driven termination)
  - gather-with-failure (one page in a batch raises)

The helper is exercised against an in-memory fake `fetch_page` so the
tests are deterministic and run in microseconds.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from automox_mcp.utils.pagination import parallel_paginate


def _make_fetcher(
    pages: list[list[int]],
    *,
    track_calls: list[int] | None = None,
):
    """Build a fake fetch_page that returns ``pages[N]`` for page N.

    Pages beyond the supplied list return ``[]`` (simulates the upstream
    serving past the last real page). If ``track_calls`` is supplied,
    each call records its page index.
    """

    async def _fetch(page_num: int) -> list[int]:
        if track_calls is not None:
            track_calls.append(page_num)
        if page_num < len(pages):
            return pages[page_num]
        return []

    return _fetch


# ---------------------------------------------------------------------------
# Single-page
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_single_page_no_parallel_batches() -> None:
    """If page 0 is short, the helper returns without firing parallel fetches."""
    calls: list[int] = []
    fetch = _make_fetcher([[1, 2, 3]], track_calls=calls)

    result = await parallel_paginate(fetch, page_size=10, max_pages=20)

    assert result == [1, 2, 3]
    assert calls == [0]  # only page 0 fetched


@pytest.mark.asyncio
async def test_single_full_page_with_no_followers() -> None:
    """Page 0 is full but page 1 onwards is empty — short-page rule terminates."""
    calls: list[int] = []
    fetch = _make_fetcher([[1, 2, 3]], track_calls=calls)

    result = await parallel_paginate(fetch, page_size=3, max_pages=20)

    # page 0 was full so we go parallel; pages 1..4 fetched and seen empty.
    assert result == [1, 2, 3]
    # Concurrency 4 by default → pages 1, 2, 3, 4 all fetched in one batch.
    # First short page (1) terminates; remaining results discarded but
    # the fetch_page calls themselves are real network round-trips that
    # the helper can't unfire. Verify that's what happens.
    assert calls == [0, 1, 2, 3, 4]


# ---------------------------------------------------------------------------
# Multi-page exhaustive
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_exact_multiple_last_page() -> None:
    """Three full pages of exactly page_size — last page's followers are empty
    pages that the helper must terminate on without dropping any data."""
    pages = [
        list(range(0, 10)),
        list(range(10, 20)),
        list(range(20, 30)),
    ]
    fetch = _make_fetcher(pages)

    result = await parallel_paginate(fetch, page_size=10, max_pages=20)

    # All 30 items returned, in page order.
    assert result == list(range(30))


@pytest.mark.asyncio
async def test_short_last_page_terminates_pagination() -> None:
    """Pages 0..2 full, page 3 short — pages 4+ should not appear."""
    pages = [
        list(range(0, 10)),  # full
        list(range(10, 20)),  # full
        list(range(20, 30)),  # full
        list(range(30, 33)),  # short — 3 items
    ]
    fetch = _make_fetcher(pages)

    result = await parallel_paginate(fetch, page_size=10, max_pages=20)

    assert result == list(range(33))


@pytest.mark.asyncio
async def test_short_page_in_batch_discards_later_prefetched_pages() -> None:
    """If page 1 is short, pages 2 and 3 (also in the same gather batch)
    must be discarded — the helper can't trust pages after a short page
    because offset pagination makes them empty or racily inconsistent."""
    pages = [
        list(range(0, 10)),  # full
        list(range(10, 15)),  # short — 5 items
        list(range(15, 25)),  # would be full but must be discarded
        list(range(25, 35)),  # would be full but must be discarded
    ]
    fetch = _make_fetcher(pages)

    result = await parallel_paginate(fetch, page_size=10, max_pages=20, concurrency=4)

    # Items from pages 0 + 1 only — pages 2 and 3 must NOT appear.
    assert result == list(range(15))


# ---------------------------------------------------------------------------
# on_page early stop
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_on_page_stops_mid_pagination() -> None:
    """The on_page callback returning True terminates pagination after the
    page it was called on."""
    pages = [
        list(range(0, 10)),
        list(range(10, 20)),
        list(range(20, 30)),
        list(range(30, 40)),
    ]
    fetch = _make_fetcher(pages)

    pages_seen_by_callback: list[int] = []

    def on_page(page_num: int, items: Any) -> bool:
        pages_seen_by_callback.append(page_num)
        return page_num == 1  # stop after seeing page 1

    result = await parallel_paginate(
        fetch, page_size=10, max_pages=20, concurrency=4, on_page=on_page
    )

    # The callback ran on page 0 then page 1, then returned True.
    assert pages_seen_by_callback == [0, 1]
    # Items from pages 0 and 1 are in the accumulator; page 2 fetched
    # in parallel but its items must not appear since on_page stopped
    # at page 1.
    assert result == list(range(20))


@pytest.mark.asyncio
async def test_on_page_fires_in_strict_page_order_under_concurrency() -> None:
    """Even when pages 1..4 complete out of order, on_page sees them in
    page-index order — important for limit-driven callers."""
    pages = [list(range(p * 10, p * 10 + 10)) for p in range(5)]

    # Reverse the completion order: page 4 returns instantly, page 0
    # returns last. But the helper still walks results in page order.
    delays = {0: 0.04, 1: 0.03, 2: 0.02, 3: 0.01, 4: 0.0}

    async def fetch(page_num: int) -> list[int]:
        await asyncio.sleep(delays[page_num])
        return pages[page_num]

    seen_order: list[int] = []

    def on_page(page_num: int, _items: Any) -> bool:
        seen_order.append(page_num)
        return False

    await parallel_paginate(fetch, page_size=10, max_pages=5, concurrency=4, on_page=on_page)

    assert seen_order == [0, 1, 2, 3, 4]


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_concurrency_bound_respected() -> None:
    """At most ``concurrency`` pages should be in flight beyond page 0 at any time."""
    in_flight = 0
    max_observed = 0
    lock = asyncio.Lock()

    pages = [list(range(p * 10, p * 10 + 10)) for p in range(10)]

    async def fetch(page_num: int) -> list[int]:
        nonlocal in_flight, max_observed
        async with lock:
            in_flight += 1
            max_observed = max(max_observed, in_flight)
        try:
            await asyncio.sleep(0.005)
            return pages[page_num] if page_num < len(pages) else []
        finally:
            async with lock:
                in_flight -= 1

    await parallel_paginate(fetch, page_size=10, max_pages=10, concurrency=3)

    # Page 0 is serial (in_flight == 1), then batches of 3 → never exceed 3.
    assert max_observed <= 3


# ---------------------------------------------------------------------------
# Gather with one failing page
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_gather_with_failure_propagates_first_exception() -> None:
    """If any page in a batch raises, the exception propagates (default
    asyncio.gather behavior). The remaining pages in the batch are
    effectively discarded — they may or may not complete, but their
    results never reach the accumulator."""
    pages = [
        list(range(0, 10)),  # page 0
        list(range(10, 20)),  # page 1 — fine
        list(range(20, 30)),  # page 2 — will raise
        list(range(30, 40)),  # page 3 — would be fine
    ]

    async def fetch(page_num: int) -> list[int]:
        if page_num == 2:
            raise RuntimeError("page 2 boom")
        return pages[page_num] if page_num < len(pages) else []

    with pytest.raises(RuntimeError, match="page 2 boom"):
        await parallel_paginate(fetch, page_size=10, max_pages=10, concurrency=4)


# ---------------------------------------------------------------------------
# Boundary conditions
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_max_pages_zero_returns_empty() -> None:
    """max_pages=0 short-circuits without even fetching page 0."""
    calls: list[int] = []
    fetch = _make_fetcher([[1, 2, 3]], track_calls=calls)

    result = await parallel_paginate(fetch, page_size=10, max_pages=0)

    assert result == []
    assert calls == []


@pytest.mark.asyncio
async def test_max_pages_one_returns_only_page_zero() -> None:
    """max_pages=1 fetches page 0 and stops, even if it was full."""
    calls: list[int] = []
    fetch = _make_fetcher([[1, 2, 3, 4, 5]], track_calls=calls)

    result = await parallel_paginate(fetch, page_size=5, max_pages=1)

    assert result == [1, 2, 3, 4, 5]
    assert calls == [0]


@pytest.mark.asyncio
async def test_empty_first_page_returns_immediately() -> None:
    """If page 0 returns no items, the helper returns without firing any
    parallel batches."""
    calls: list[int] = []
    fetch = _make_fetcher([[]], track_calls=calls)

    result = await parallel_paginate(fetch, page_size=10, max_pages=20)

    assert result == []
    assert calls == [0]
