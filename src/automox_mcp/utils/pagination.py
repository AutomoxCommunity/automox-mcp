"""Concurrent pagination helper for upstream endpoints with bounded parallelism.

Used by ``summarize_device_health``, ``list_device_inventory``, and
``search_devices`` to fetch their pages of ``/servers`` in parallel rather
than serially. On big tenants (multi-thousand-device fleets) the serial
loop dominated wall time at 50-500 ms per page × up to 20 pages — this
helper roughly halves that by overlapping requests.

Two pagination styles are supported through one entry point:

1. **Exhaustive** — fetch every page until a short page (fewer items than
   ``page_size``) signals the end. Default behavior: the helper returns
   the flattened item list. Used when every record matters
   (fleet-wide aggregation).
2. **Driven by a per-page callback** — pass ``on_page``. The callback is
   invoked once per page in strict page order, even when the underlying
   fetches were in parallel. Return ``True`` from the callback to
   terminate pagination. Used for workflows that filter client-side and
   have a target count: the callback can mutate workflow-local state
   (accumulator, counters) and decide when enough has been seen.

In both modes, pages 1..N are fetched concurrently in batches of
``concurrency``. The first short page in a batch terminates pagination;
any prefetched pages after the short page are discarded.

Page 0 is always fetched serially: a single-page tenant should not pay
the cost of warming a gather, and the helper needs to see page 0's
length to know whether to spin up parallelism at all.

Issue #69 — design + rationale documented inline.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

T = TypeVar("T")

# Default in-flight cap. The Automox upstream has no documented per-org
# concurrency limit and our local rate limiter applies at the tool-call
# boundary (one slot per invocation), not per upstream request — so this
# bound is purely a backpressure guard against unbounded RAM/socket use.
# 4 covers the common case (5-20 page fleets) without blasting upstream.
_DEFAULT_CONCURRENCY = 4


async def parallel_paginate(
    fetch_page: Callable[[int], Awaitable[Sequence[T]]],
    *,
    page_size: int,
    max_pages: int,
    concurrency: int = _DEFAULT_CONCURRENCY,
    on_page: Callable[[int, Sequence[T]], bool] | None = None,
) -> list[T]:
    """Fetch pages from ``fetch_page`` with bounded concurrency.

    Page 0 is fetched serially. If it returns ``< page_size`` items, the
    function returns immediately. Otherwise pages ``1..concurrency`` are
    fetched concurrently via :func:`asyncio.gather`. Results are walked in
    page order; the first short page terminates pagination and any
    prefetched pages after it are discarded.

    Args:
        fetch_page: Async callable taking a 0-indexed page number and
            returning that page's items.
        page_size: Expected items per full page. A page with fewer items
            signals end-of-data.
        max_pages: Hard safety cap on total pages fetched. Set generously;
            the helper short-circuits as soon as a short page or
            ``on_page`` triggers.
        concurrency: Maximum number of pages in flight beyond page 0.
            Default ``4``. Set lower (``1-2``) for workflows where each
            page is large or where over-fetch has bandwidth cost.
        on_page: Optional callback invoked once per page in strict page
            order. Called as ``on_page(page_num, items)`` and may
            mutate workflow-local state. Return ``True`` to terminate
            pagination. Useful for limit-driven workflows where the
            caller filters client-side and has a target count.

    Returns:
        All accumulated items across pages, in page order. When
        ``on_page`` mutates workflow-local state, the caller often
        ignores the returned list and reads its own accumulator instead.

    Raises:
        Whatever ``fetch_page`` raises. :func:`asyncio.gather` re-raises
        the first exception in a batch; later exceptions are discarded
        with their corresponding pages.
    """
    if max_pages <= 0:
        return []

    accumulated: list[T] = []

    # Page 0 first — cheap fast path for single-page tenants and a clean
    # signal of whether parallelism is worth setting up.
    page_zero = list(await fetch_page(0))
    accumulated.extend(page_zero)
    if on_page is not None and on_page(0, page_zero):
        return accumulated
    if len(page_zero) < page_size:
        return accumulated
    if max_pages == 1:
        return accumulated

    next_page = 1
    while next_page < max_pages:
        batch_end = min(next_page + concurrency, max_pages)
        batch_indices = list(range(next_page, batch_end))
        # gather preserves submission order in the results list, so we
        # can walk results in page-index order and apply the "discard
        # everything after a short page" rule deterministically.
        batch_results = await asyncio.gather(*(fetch_page(p) for p in batch_indices))

        for page_num, items in zip(batch_indices, batch_results, strict=True):
            items_list = list(items)
            accumulated.extend(items_list)
            if on_page is not None and on_page(page_num, items_list):
                return accumulated
            if len(items_list) < page_size:
                # Short page — any prefetched pages after this one are
                # discarded (intentionally; offset pagination makes them
                # either empty or racily inconsistent).
                return accumulated

        next_page = batch_end

    return accumulated


__all__ = ["parallel_paginate"]
