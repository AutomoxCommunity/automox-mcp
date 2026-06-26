"""Regression tests for list_events count mislabeling.

The live ``/events`` endpoint returns a bare JSON list with no upstream total,
so ``len(page)`` is a per-page count, NOT an org-wide grand total. Presenting
it as ``total_events`` under-reported by a page on any limited query. The fix
renames the per-page count to ``events_returned`` (reserving ``total_events``
for count mode, where upstream actually supplies a real total under ``size``)
and adds a canonical ``metadata.pagination`` block plus ``suggested_next_call``.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.events import list_events


def _event(event_id: int) -> dict[str, Any]:
    return {
        "id": event_id,
        "name": "patch.success",
        "server_id": 10,
        "server_name": "web-01",
        "policy_id": 5,
        "policy_name": "Weekly Patches",
        "policy_type_name": "patch",
        "user_id": 99,
        "data": None,
        "create_time": "2026-03-01T00:00:00Z",
    }


@pytest.mark.asyncio
async def test_bare_list_reports_events_returned_not_total():
    """A bare-list /events response names the count `events_returned`.

    There is no upstream total, so no `total_events` may claim a grand total.
    """
    page = [_event(1), _event(2), _event(3)]
    client = StubClient(get_responses={"/events": [page]})

    result = await list_events(cast(AutomoxClient, client), org_id=42)

    data = result["data"]
    assert data["events_returned"] == 3
    assert "total_events" not in data
    assert len(data["events"]) == 3


@pytest.mark.asyncio
async def test_full_page_emits_pagination_and_suggested_next_call():
    """A full page (returned == limit) signals more pages.

    Pagination state lands under `metadata.pagination` and the next-page
    invocation under `metadata.suggested_next_call`.
    """
    page = [_event(i) for i in range(5)]
    client = StubClient(get_responses={"/events": [page]})

    result = await list_events(
        cast(AutomoxClient, client),
        org_id=42,
        page=0,
        limit=5,
        event_name="patch.success",
    )

    metadata = result["metadata"]
    pagination = metadata["pagination"]
    assert pagination["page"] == 0
    assert pagination["page_size"] == 5
    assert pagination["has_more"] is True
    assert pagination["returned_count"] == 5
    assert pagination["next_page"] == 1

    suggested = metadata["suggested_next_call"]
    assert suggested["tool"] == "list_events"
    assert suggested["args"]["page"] == 1
    assert suggested["args"]["limit"] == 5
    # Active filters are carried forward so the next page stays scoped.
    assert suggested["args"]["event_name"] == "patch.success"


@pytest.mark.asyncio
async def test_partial_page_has_no_more_and_no_suggestion():
    """A short page (returned < limit) is the last page: no next call."""
    page = [_event(1), _event(2)]
    client = StubClient(get_responses={"/events": [page]})

    result = await list_events(cast(AutomoxClient, client), org_id=42, page=0, limit=25)

    metadata = result["metadata"]
    assert metadata["pagination"]["has_more"] is False
    assert "suggested_next_call" not in metadata
    assert result["data"]["events_returned"] == 2


@pytest.mark.asyncio
async def test_count_only_reports_real_total_and_suppresses_events():
    """Count mode supplies a real total under `size`; events array suppressed.

    Fixture is the live count-mode shape: total under `size`, empty `results`.
    """
    count_payload = {"size": 1382, "results": []}
    client = StubClient(get_responses={"/events": [count_payload]})

    result = await list_events(
        cast(AutomoxClient, client),
        org_id=42,
        count_only=True,
    )

    data = result["data"]
    # Only count mode may claim a grand total.
    assert data["total_events"] == 1382
    assert data["events"] == []
    assert "events_returned" not in data
