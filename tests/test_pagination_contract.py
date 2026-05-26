"""Cross-tool contract test: every paginated workflow emits the canonical
``metadata.pagination`` block (issue #52).

The block is keyed under ``metadata.pagination`` with a stable set of canonical
fields:

  - ``page``           offset-pagination page number (0-indexed)
  - ``page_size``      records per page (alias for ``limit``)
  - ``total_elements`` total records across all pages (when knowable)
  - ``total_pages``    total pages (when knowable)
  - ``has_more``       whether another page exists
  - ``next_cursor``    cursor for cursor-based pagination

Each workflow may legitimately omit fields that aren't applicable to its
pagination style (e.g. cursor-based tools omit ``page``/``total_elements``),
but every paginated tool MUST emit the block under that key and use this
vocabulary — not legacy aliases like ``current_page``/``total_count``/etc.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.audit_v2 import audit_events_ocsf
from automox_mcp.workflows.device_search import get_device_assignments
from automox_mcp.workflows.policy import summarize_policies
from automox_mcp.workflows.policy_history import list_policy_runs_v2
from automox_mcp.workflows.policy_windows import search_policy_windows
from automox_mcp.workflows.webhooks import list_webhooks

_ORG_UUID = "11111111-2222-3333-4444-555555555555"

# Canonical field vocabulary. Only fields from this set count as
# "canonical" — anything else (current_page, total_count, limit, …) is a
# legacy alias and may live alongside but does not satisfy the contract.
_CANONICAL_FIELDS = {
    "page",
    "page_size",
    "total_elements",
    "total_pages",
    "has_more",
    "next_cursor",
}


def _assert_canonical_pagination(metadata: dict[str, Any], *, expect: set[str]) -> None:
    """Assert ``metadata.pagination`` exists and contains the expected canonical
    fields drawn from the official vocabulary."""
    assert "pagination" in metadata, "metadata.pagination is missing"
    block = metadata["pagination"]
    assert isinstance(block, dict), f"pagination must be a dict, got {type(block).__name__}"
    keys = set(block.keys())
    canonical_present = keys & _CANONICAL_FIELDS
    assert expect <= canonical_present, (
        f"missing canonical fields {expect - canonical_present} "
        f"(got canonical: {sorted(canonical_present)}, all: {sorted(keys)})"
    )


def _make_org_uuid_client(**kwargs: Any) -> StubClient:
    client = StubClient(**kwargs)
    client.org_uuid = _ORG_UUID  # type: ignore[attr-defined]
    return client


# ---------------------------------------------------------------------------
# Offset-paginated tools — page / page_size / total_* / has_more
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_policy_catalog_emits_canonical_pagination() -> None:
    """summarize_policies (policy_catalog) — offset pagination on /policies."""
    stub = StubClient(get_responses={"/policies": [[]]})
    stub.org_id = 42  # type: ignore[attr-defined]
    result = await summarize_policies(cast(AutomoxClient, stub), org_id=42, limit=10, page=0)
    _assert_canonical_pagination(
        result["metadata"], expect={"page", "page_size", "has_more"}
    )


@pytest.mark.asyncio
async def test_policy_runs_v2_emits_canonical_pagination_when_filtering() -> None:
    """list_policy_runs_v2 — client-side pagination when a filter is active."""
    runs = [
        {"policy_uuid": f"p{i}", "policy_name": f"n-{i}", "policy_type": "custom"}
        for i in range(15)
    ]
    client = _make_org_uuid_client(get_responses={"/policy-history/policy-runs": [runs]})
    result = await list_policy_runs_v2(
        cast(AutomoxClient, client),
        org_id=42,
        policy_type="custom",
        limit=10,
        page=0,
    )
    _assert_canonical_pagination(
        result["metadata"],
        expect={"page", "page_size", "total_elements", "total_pages", "has_more"},
    )


@pytest.mark.asyncio
async def test_search_policy_windows_emits_canonical_pagination() -> None:
    """search_policy_windows — Spring page envelope normalized into metadata."""
    response = {
        "content": [],
        "total_elements": 42,
        "total_pages": 5,
    }
    client = StubClient(
        post_responses={f"/policy-windows/org/{_ORG_UUID}/search": [response]},
    )
    client.org_uuid = _ORG_UUID  # type: ignore[attr-defined]

    result = await search_policy_windows(
        cast(AutomoxClient, client),
        org_uuid=_ORG_UUID,
        page=0,
        size=10,
    )
    _assert_canonical_pagination(
        result["metadata"],
        expect={"page", "page_size", "total_elements", "total_pages"},
    )


@pytest.mark.asyncio
async def test_get_device_assignments_emits_canonical_pagination() -> None:
    """get_device_assignments — Spring Page<T> envelope from server-groups-api."""
    response = {
        "content": [],
        "number": 0,
        "size": 25,
        "total_elements": 100,
        "total_pages": 4,
        "first": True,
        "last": False,
        "pageable": {"page_number": 0, "offset": 0},
    }
    path = f"/server-groups-api/v1/organizations/{_ORG_UUID}/assignments"
    client = StubClient(get_responses={path: [response]})
    client.org_uuid = _ORG_UUID  # type: ignore[attr-defined]
    client.org_id = 42  # type: ignore[attr-defined]

    result = await get_device_assignments(cast(AutomoxClient, client), org_id=42)
    _assert_canonical_pagination(
        result["metadata"],
        expect={"page", "page_size", "total_elements", "total_pages", "has_more"},
    )


# ---------------------------------------------------------------------------
# Cursor-paginated tools — page_size / has_more / next_cursor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_webhooks_emits_canonical_pagination() -> None:
    """list_webhooks — cursor-based pagination on /organizations/{uuid}/webhooks."""
    response = {"data": [], "nextCursor": "abc123"}
    client = StubClient(get_responses={f"/organizations/{_ORG_UUID}/webhooks": [response]})
    result = await list_webhooks(cast(AutomoxClient, client), org_uuid=_ORG_UUID, limit=25)
    _assert_canonical_pagination(
        result["metadata"], expect={"page_size", "has_more", "next_cursor"}
    )


@pytest.mark.asyncio
async def test_audit_events_ocsf_emits_canonical_pagination() -> None:
    """audit_events_ocsf — cursor-based pagination on audit-service/v1."""
    response = {
        "data": [],
        "metadata": {"next": "cursor-value"},
    }
    client = StubClient(
        get_responses={f"/audit-service/v1/orgs/{_ORG_UUID}/events": [response]},
    )
    client.org_uuid = _ORG_UUID  # type: ignore[attr-defined]
    result = await audit_events_ocsf(
        cast(AutomoxClient, client),
        org_id=42,
        date="2026-05-01",
        limit=50,
    )
    _assert_canonical_pagination(
        result["metadata"], expect={"page_size", "has_more", "next_cursor"}
    )
