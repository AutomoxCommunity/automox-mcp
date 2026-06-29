"""Tests for pagination/contract honesty in device health and needs-attention.

Covers three behavioral guarantees:

* ``list_devices_needing_attention`` walks every offset page to completion, so
  a fleet with more flagged devices than one page reads as complete rather
  than silently truncated. When the internal page cap is hit before the report
  is exhausted, it reports ``has_more`` plus a resume offset instead.
* ``summarize_device_health`` treats ``limit`` as a cap on the number of
  devices sampled into the aggregate (its documented contract), not as the
  upstream page size.
* ``summarize_device_health`` flags ``response_truncated`` only when it
  actually drops data from the payload.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.devices import (
    list_devices_needing_attention,
    summarize_device_health,
)

_NEEDS_ATTENTION_PATH = "/reports/needs-attention"


def _flagged_device(device_id: int) -> dict[str, Any]:
    """A minimal non-compliant needs-attention report row."""
    return {
        "id": device_id,
        "name": f"host-{device_id}",
        "compliant": False,
        "groupId": 7,
        "lastRefreshTime": "2026-05-07T12:00:00+0000",
    }


def _needs_attention_page(device_ids: list[int]) -> dict[str, Any]:
    return {"data": [_flagged_device(i) for i in device_ids]}


def _health_device(device_id: int) -> dict[str, Any]:
    """A managed device with a recent check-in (never stale)."""
    return {
        "id": device_id,
        "name": f"host-{device_id}",
        "managed": True,
        "compliant": True,
        "os_name": "Windows",
        "status": {"policy_status": "compliant"},
        "last_check_in": "2026-05-10T12:00:00Z",
    }


# ===========================================================================
# list_devices_needing_attention — completeness over a single page
# ===========================================================================


@pytest.mark.asyncio
async def test_needs_attention_over_limit_walks_all_pages_and_reads_complete() -> None:
    """More flagged devices than one page → every page walked, has_more False.

    With ``limit=2``: page 0 is full (2 rows) so a second page is fetched;
    page 1 is short (1 row) which ends the walk. All three devices come back
    and the response is honestly reported as complete.
    """
    client = StubClient(
        get_responses={
            _NEEDS_ATTENTION_PATH: [
                _needs_attention_page([1, 2]),  # full page → walk continues
                _needs_attention_page([3]),  # short page → walk ends
            ]
        }
    )

    result = await list_devices_needing_attention(cast(AutomoxClient, client), org_id=42, limit=2)

    data = result["data"]
    assert data["returned_count"] == 3
    assert [d["device_id"] for d in data["devices"]] == [1, 2, 3]

    pagination = result["metadata"]["pagination"]
    assert pagination["has_more"] is False
    assert pagination["pages_walked"] == 2
    # A complete walk advertises no resume offset and no follow-up call.
    assert "next_offset" not in pagination
    assert "suggested_next_call" not in result["metadata"]

    # Offsets advanced by the page size on each request.
    offsets = [
        params["offset"] for _method, path, params in client.calls if path == _NEEDS_ATTENTION_PATH
    ]
    assert offsets == [0, 2]


@pytest.mark.asyncio
async def test_needs_attention_hits_page_cap_reports_more_available() -> None:
    """If every walked page stays full, the page cap is honestly surfaced.

    Feeding only full pages (``limit`` rows each) never produces the short
    page that ends the walk, so the internal page cap is reached. The wrapper
    must then report ``has_more`` and a resume offset rather than claiming the
    report was exhausted.
    """
    # Enough full pages to exceed the internal page cap.
    full_pages = [_needs_attention_page([1, 2]) for _ in range(40)]
    client = StubClient(get_responses={_NEEDS_ATTENTION_PATH: full_pages})

    result = await list_devices_needing_attention(cast(AutomoxClient, client), org_id=42, limit=2)

    pagination = result["metadata"]["pagination"]
    assert pagination["has_more"] is True
    # Resume offset = pages walked * page size, so a follow-up continues
    # exactly where this call stopped.
    assert pagination["next_offset"] == pagination["pages_walked"] * 2
    assert result["data"]["returned_count"] == pagination["pages_walked"] * 2


# ===========================================================================
# summarize_device_health — limit is a sample cap, not a page size
# ===========================================================================


@pytest.mark.asyncio
async def test_health_limit_caps_sampled_devices() -> None:
    """``limit`` bounds how many devices are aggregated (its documented contract)."""
    devices = [_health_device(i) for i in range(10)]
    client = StubClient(get_responses={"/servers": [devices]})
    reference_time = datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC)

    result = await summarize_device_health(
        cast(AutomoxClient, client),
        org_id=42,
        limit=4,
        current_time=reference_time,
    )

    meta = result["metadata"]
    # Exactly `limit` devices feed the aggregate, even though more were fetched.
    assert meta["effective_limit"] == 4
    assert meta["sampled_device_count"] == 4
    assert meta["fetched_device_count"] == 10
    # The aggregate counts reflect only the sampled cap.
    assert result["data"]["total_devices"] == 4


@pytest.mark.asyncio
async def test_health_none_limit_samples_full_upstream_cap() -> None:
    """A null/omitted limit defaults to the upstream max sample size."""
    devices = [_health_device(i) for i in range(3)]
    client = StubClient(get_responses={"/servers": [devices]})
    reference_time = datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC)

    result = await summarize_device_health(
        cast(AutomoxClient, client),
        org_id=42,
        limit=None,
        current_time=reference_time,
    )

    meta = result["metadata"]
    assert meta["effective_limit"] == 500
    assert meta["sampled_device_count"] == 3
    assert result["data"]["total_devices"] == 3


# ===========================================================================
# summarize_device_health — response_truncated implies data was dropped
# ===========================================================================


def _stale_device(device_id: int) -> dict[str, Any]:
    """A device whose last check-in is far past the stale threshold."""
    return {
        "id": device_id,
        "name": "stale-" + "x" * 300 + f"-{device_id}",
        "managed": True,
        "compliant": True,
        "os_name": "Windows",
        "status": {"policy_status": "compliant"},
        "last_check_in": "2024-01-01T12:00:00Z",
    }


@pytest.mark.asyncio
async def test_health_response_truncated_only_when_data_dropped() -> None:
    """An oversized response actually sheds the stale_devices list before flagging.

    The stale list (long names, well past the threshold) pushes the payload
    over the byte budget. The truncation path must drop that list and record
    how many entries were shed — not flag truncation while shipping the data.
    """
    devices = [_stale_device(i) for i in range(80)]
    client = StubClient(get_responses={"/servers": [devices]})
    reference_time = datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC)

    result = await summarize_device_health(
        cast(AutomoxClient, client),
        org_id=42,
        max_stale_devices=None,  # include all stale devices → oversized payload
        current_time=reference_time,
    )

    meta = result["metadata"]
    assert meta["response_truncated"] is True
    # The flag implies the data was genuinely removed.
    assert result["data"]["stale_devices"] == []
    assert meta["stale_devices_dropped_for_size"] == 80
    # The true count is preserved so the information is not lost outright.
    assert meta["stale_device_count"] == 80


@pytest.mark.asyncio
async def test_health_small_response_not_flagged_truncated() -> None:
    """A response within budget never claims truncation."""
    devices = [_health_device(i) for i in range(3)]
    client = StubClient(get_responses={"/servers": [devices]})
    reference_time = datetime(2026, 5, 11, 12, 0, 0, tzinfo=UTC)

    result = await summarize_device_health(
        cast(AutomoxClient, client),
        org_id=42,
        current_time=reference_time,
    )

    meta = result["metadata"]
    assert "response_truncated" not in meta
    assert "stale_devices_dropped_for_size" not in meta
