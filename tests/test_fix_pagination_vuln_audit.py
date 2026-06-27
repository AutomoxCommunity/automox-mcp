"""Pagination-honesty tests for the vuln-sync and audit-v2 list workflows.

These list endpoints used to report ``len(page)`` under grand-total-sounding
keys (``total_action_sets`` / ``total_issues`` / ``total_solutions`` /
``total_events``) even though the upstream supplies no grand total and the page
may be a slice of a larger set. A caller reading those keys would mistake a
single page for the whole result.

The fix renames the per-page count to a per-page-honest name
(``*_returned`` / ``events_returned``), adds a ``metadata.pagination`` block,
and emits ``metadata.suggested_next_call`` when a full page implies more pages.
These tests assert that contract from inputs to outputs against a StubClient.
"""

from typing import Any, cast

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.audit_v2 import audit_events_ocsf
from automox_mcp.workflows.vuln_sync import (
    get_action_set_issues,
    get_action_set_solutions,
    list_remediation_action_sets,
)

_ORG_UUID = "11111111-2222-3333-4444-555555555555"


def _rows(n: int) -> list[dict[str, Any]]:
    return [{"id": i} for i in range(n)]


# ---------------------------------------------------------------------------
# vuln_sync — list_remediation_action_sets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_action_sets_uses_returned_name_not_grand_total() -> None:
    path = "/orgs/42/remediations/action-sets"
    client = StubClient(get_responses={path: [_rows(3)]})
    result = await list_remediation_action_sets(cast(AutomoxClient, client), org_id=42)

    data = result["data"]
    # The honest per-page count is the canonical key.
    assert data["action_sets_returned"] == 3
    # A pagination block is always present.
    assert "pagination" in result["metadata"]


@pytest.mark.asyncio
async def test_action_sets_full_page_suggests_next_call() -> None:
    path = "/orgs/42/remediations/action-sets"
    client = StubClient(get_responses={path: [_rows(5)]})
    result = await list_remediation_action_sets(
        cast(AutomoxClient, client), org_id=42, page=0, limit=5
    )

    pagination = result["metadata"]["pagination"]
    assert pagination["has_more"] is True
    nxt = result["metadata"]["suggested_next_call"]
    assert nxt["tool"] == "list_remediation_action_sets"
    assert nxt["args"]["page"] == 1
    assert nxt["args"]["limit"] == 5


@pytest.mark.asyncio
async def test_action_sets_short_page_has_no_next_call() -> None:
    path = "/orgs/42/remediations/action-sets"
    client = StubClient(get_responses={path: [_rows(2)]})
    result = await list_remediation_action_sets(
        cast(AutomoxClient, client), org_id=42, page=0, limit=5
    )

    assert result["metadata"]["pagination"]["has_more"] is False
    assert "suggested_next_call" not in result["metadata"]


# ---------------------------------------------------------------------------
# vuln_sync — get_action_set_issues
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_issues_uses_returned_name() -> None:
    path = "/orgs/42/remediations/action-sets/7/issues"
    client = StubClient(get_responses={path: [_rows(4)]})
    result = await get_action_set_issues(cast(AutomoxClient, client), org_id=42, action_set_id=7)

    assert result["data"]["issues_returned"] == 4
    assert "pagination" in result["metadata"]


@pytest.mark.asyncio
async def test_issues_full_page_suggests_next_call_with_action_set_id() -> None:
    path = "/orgs/42/remediations/action-sets/7/issues"
    client = StubClient(get_responses={path: [_rows(3)]})
    result = await get_action_set_issues(
        cast(AutomoxClient, client), org_id=42, action_set_id=7, page=2, limit=3
    )

    nxt = result["metadata"]["suggested_next_call"]
    assert nxt["tool"] == "get_action_set_issues"
    assert nxt["args"] == {"action_set_id": 7, "page": 3, "limit": 3}


# ---------------------------------------------------------------------------
# vuln_sync — get_action_set_solutions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_solutions_uses_returned_name() -> None:
    path = "/orgs/42/remediations/action-sets/7/solutions"
    client = StubClient(get_responses={path: [_rows(2)]})
    result = await get_action_set_solutions(cast(AutomoxClient, client), org_id=42, action_set_id=7)

    assert result["data"]["solutions_returned"] == 2
    assert "pagination" in result["metadata"]


@pytest.mark.asyncio
async def test_solutions_full_page_suggests_next_call() -> None:
    path = "/orgs/42/remediations/action-sets/7/solutions"
    client = StubClient(get_responses={path: [_rows(10)]})
    result = await get_action_set_solutions(
        cast(AutomoxClient, client), org_id=42, action_set_id=7, page=0, limit=10
    )

    assert result["metadata"]["pagination"]["has_more"] is True
    nxt = result["metadata"]["suggested_next_call"]
    assert nxt["tool"] == "get_action_set_solutions"
    assert nxt["args"] == {"action_set_id": 7, "page": 1, "limit": 10}


# ---------------------------------------------------------------------------
# audit_v2 — audit_events_ocsf
# ---------------------------------------------------------------------------


def _event(uid: str) -> dict[str, Any]:
    return {
        "_id": uid,
        "metadata": {"uid": uid},
        "type_name": "Authentication: Logon",
        "activity": "Logon",
    }


@pytest.mark.asyncio
async def test_events_uses_returned_name_not_grand_total() -> None:
    path = f"/audit-service/v1/orgs/{_ORG_UUID}/events"
    client = StubClient(get_responses={path: [[_event("a"), _event("b")]]})
    client.org_uuid = _ORG_UUID
    result = await audit_events_ocsf(cast(AutomoxClient, client), org_id=42, date="2026-03-25")

    # The per-page-honest key reports this page's filtered count.
    assert result["data"]["events_returned"] == 2
    assert "pagination" in result["metadata"]


@pytest.mark.asyncio
async def test_events_more_pages_signalled_when_cursor_present() -> None:
    """A next cursor (here derived from the last event) means has_more=True, so
    a sub-total must never be presented as the date-wide grand total."""
    path = f"/audit-service/v1/orgs/{_ORG_UUID}/events"
    client = StubClient(get_responses={path: [[_event("a"), _event("last-cursor")]]})
    client.org_uuid = _ORG_UUID
    result = await audit_events_ocsf(
        cast(AutomoxClient, client), org_id=42, date="2026-03-25", limit=2
    )

    pagination = result["metadata"]["pagination"]
    assert pagination["has_more"] is True
    assert pagination["next_cursor"] == "last-cursor"
    # events_returned is honest about being a single page's count.
    assert result["data"]["events_returned"] == 2
