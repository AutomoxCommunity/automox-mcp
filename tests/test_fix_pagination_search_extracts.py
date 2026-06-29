"""Pagination-honesty regression tests for device-search and data-extract lists.

These cover the cases where a per-page count was previously presented as a
grand total, and where a full page advertised more results without telling the
caller how to fetch them:

- ``get_device_assignments`` surfaces the true grand total from the Spring
  ``total_elements`` (not the page length) and emits ``suggested_next_call``
  when more pages remain.
- ``run_saved_search`` emits ``suggested_next_call`` for the next page whenever
  ``has_more`` is true, and reports the grand total separately from the page count.
- ``list_data_extracts`` on a bare-list response (no ``{results, size}``
  envelope) reports the page count under ``extracts_returned`` rather than
  mislabelling it as a grand ``total_extracts``.
"""

from typing import Any, cast

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.data_extracts import list_data_extracts
from automox_mcp.workflows.device_search import (
    get_device_assignments,
    run_saved_search,
)

_ORG_UUID = "11111111-2222-3333-4444-555555555555"


def _make_client(**kwargs: Any) -> StubClient:
    client = StubClient(**kwargs)
    client.org_uuid = _ORG_UUID
    return client


# ---------------------------------------------------------------------------
# get_device_assignments — grand total + continuation hint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assignments_grand_total_from_total_elements_with_next_call() -> None:
    """A partial first page reports the fleet-wide grand total from
    ``total_elements`` (not the 2 rows on this page) and tells the caller how
    to fetch the next page."""
    path = f"/server-groups-api/v1/organizations/{_ORG_UUID}/assignments"
    page_zero = {
        "content": [
            {"device_uuid": "dev-1", "policy_id": 1},
            {"device_uuid": "dev-2", "policy_id": 2},
        ],
        "number": 0,
        "size": 2,
        "total_elements": 5,
        "total_pages": 3,
        "first": True,
        "last": False,
    }
    client = _make_client(get_responses={path: [page_zero]})
    result = await get_device_assignments(cast(AutomoxClient, client), limit=2)

    # Grand total is the whole fleet, not this page.
    assert result["data"]["total_assignments"] == 5
    assert result["data"]["assignments_returned"] == 2

    next_call = result["metadata"]["suggested_next_call"]
    assert next_call["tool"] == "get_device_assignments"
    assert next_call["args"] == {"page": 1, "limit": 2}


@pytest.mark.asyncio
async def test_assignments_last_page_has_no_next_call() -> None:
    """On the final page no continuation hint is emitted."""
    path = f"/server-groups-api/v1/organizations/{_ORG_UUID}/assignments"
    last_page = {
        "content": [{"device_uuid": "dev-9", "policy_id": 9}],
        "number": 2,
        "size": 2,
        "total_elements": 5,
        "total_pages": 3,
        "first": False,
        "last": True,
    }
    client = _make_client(get_responses={path: [last_page]})
    result = await get_device_assignments(cast(AutomoxClient, client), page=2, limit=2)

    assert result["data"]["total_assignments"] == 5
    assert result["data"]["assignments_returned"] == 1
    assert "suggested_next_call" not in result["metadata"]


@pytest.mark.asyncio
async def test_assignments_forwards_page_and_limit_upstream() -> None:
    """``page``/``limit`` reach the upstream request as query params."""
    path = f"/server-groups-api/v1/organizations/{_ORG_UUID}/assignments"
    client = _make_client(
        get_responses={path: [{"content": [], "total_elements": 0, "last": True}]}
    )
    await get_device_assignments(cast(AutomoxClient, client), page=3, limit=25)

    _, _path, params = client.calls[0]
    assert params == {"page": 3, "limit": 25}


# ---------------------------------------------------------------------------
# run_saved_search — continuation hint when more pages remain
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_saved_search_has_more_emits_next_call() -> None:
    """When the Spring page reports ``last=false`` the next-page call is
    suggested and the grand total comes from ``total_elements``."""
    search_id = "ss-100"
    path = f"/server-groups-api/v1/organizations/{_ORG_UUID}/device/search/{search_id}"
    page_obj = {
        "content": [{"id": 1, "hostname": "host-a"}, {"id": 2, "hostname": "host-b"}],
        "number": 0,
        "size": 2,
        "total_elements": 7,
        "total_pages": 4,
        "first": True,
        "last": False,
    }
    client = _make_client(get_responses={path: [page_obj]})
    result = await run_saved_search(
        cast(AutomoxClient, client),
        search_id=search_id,
        page=0,
        size=2,
        fields=["hostname"],
    )

    assert result["data"]["total_devices"] == 7
    assert result["data"]["devices_returned"] == 2
    assert result["metadata"]["pagination"]["has_more"] is True

    next_call = result["metadata"]["suggested_next_call"]
    assert next_call["tool"] == "run_saved_search"
    assert next_call["args"] == {
        "search_id": search_id,
        "page": 1,
        "size": 2,
        "fields": ["hostname"],
    }


# ---------------------------------------------------------------------------
# list_data_extracts — bare list reports a per-page count, not a grand total
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_data_extracts_bare_list_reports_extracts_returned() -> None:
    """A bare list (no ``{results, size}`` envelope) carries no upstream grand
    total, so the page count is reported under ``extracts_returned`` rather than
    being mislabelled as a fleet-wide ``total_extracts``."""
    bare = [
        {"id": "e-1", "status": "complete", "is_completed": True},
        {"id": "e-2", "status": "expired", "is_completed": False},
    ]
    client = StubClient(get_responses={"/data-extracts": [bare]})
    result = await list_data_extracts(cast(AutomoxClient, client), org_id=42)

    assert result["data"]["extracts_returned"] == 2
    # No envelope `size` was present, so there is no honest grand total to
    # surface; `total_extracts` (if present) is only a deprecated back-compat
    # alias and must NOT exceed the page length.
    assert result["data"].get("total_extracts", 2) == 2


@pytest.mark.asyncio
async def test_data_extracts_envelope_reports_total_from_size() -> None:
    """With the ``{results, size}`` envelope, ``total_extracts`` is the real
    grand total (``size``) and ``extracts_returned`` is the page length."""
    envelope = {
        "results": [{"id": "e-1", "status": "complete", "is_completed": True}],
        "size": 12,
    }
    client = StubClient(get_responses={"/data-extracts": [envelope]})
    result = await list_data_extracts(cast(AutomoxClient, client), org_id=42)

    assert result["data"]["total_extracts"] == 12
    assert result["data"]["extracts_returned"] == 1
