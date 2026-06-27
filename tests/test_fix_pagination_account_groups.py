"""Pagination/count-honesty tests for list tools.

Each list tool that returns a single page must report the page count under a
``*_returned`` name (never a grand-total name), carry a ``metadata.pagination``
block, hand back a ``suggested_next_call`` when more pages are available, and
surface a real ``total_*`` only when the upstream actually supplies one.

These assert inputs -> outputs only, with the upstream stubbed via StubClient.
"""

from __future__ import annotations

from typing import cast

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.account import (
    list_organizations,
    list_user_api_keys,
    list_users,
)
from automox_mcp.workflows.groups import list_server_groups
from automox_mcp.workflows.webhooks import list_webhooks

_ORG_UUID = "11111111-2222-3333-4444-555555555555"


def _user(uid: int) -> dict:
    return {"id": uid, "email": f"u{uid}@example.com"}


def _group(gid: int) -> dict:
    return {"id": gid, "name": f"group-{gid}", "refresh_interval": 1440}


# ---------------------------------------------------------------------------
# list_users
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_users_page_count_is_returned_not_total() -> None:
    client = StubClient(get_responses={"/users": [[_user(1), _user(2)]]})
    result = await list_users(cast(AutomoxClient, client), org_id=42)

    # Page count lives under the *_returned name.
    assert result["data"]["users_returned"] == 2
    # A pagination block is always present.
    assert "pagination" in result["metadata"]
    # No upstream total for a bare-list endpoint: no honest grand total exists,
    # so the pagination block carries no total_elements.
    assert "total_elements" not in result["metadata"]["pagination"]


@pytest.mark.asyncio
async def test_list_users_suggests_next_call_on_full_page() -> None:
    # A full page (len == limit) implies more may follow.
    client = StubClient(get_responses={"/users": [[_user(1), _user(2)]]})
    result = await list_users(cast(AutomoxClient, client), org_id=42, page=0, limit=2)

    assert result["metadata"]["pagination"]["has_more"] is True
    hint = result["metadata"]["suggested_next_call"]
    assert hint["tool"] == "list_users"
    assert hint["args"]["page"] == 1
    assert hint["args"]["limit"] == 2


@pytest.mark.asyncio
async def test_list_users_no_next_call_on_short_page() -> None:
    # A short page (len < limit) is the last page.
    client = StubClient(get_responses={"/users": [[_user(1)]]})
    result = await list_users(cast(AutomoxClient, client), org_id=42, page=0, limit=5)

    assert result["metadata"]["pagination"]["has_more"] is False
    assert "suggested_next_call" not in result["metadata"]


# ---------------------------------------------------------------------------
# list_organizations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_organizations_page_count_is_returned_not_total() -> None:
    client = StubClient(get_responses={"/orgs": [[{"id": 1}, {"id": 2}]]})
    result = await list_organizations(cast(AutomoxClient, client))

    assert result["data"]["organizations_returned"] == 2
    assert "total_organizations" not in result["data"]
    assert "pagination" in result["metadata"]
    assert "total_elements" not in result["metadata"]["pagination"]


@pytest.mark.asyncio
async def test_list_organizations_suggests_next_call_on_full_page() -> None:
    client = StubClient(get_responses={"/orgs": [[{"id": 1}, {"id": 2}]]})
    result = await list_organizations(cast(AutomoxClient, client), page=0, limit=2)

    assert result["metadata"]["pagination"]["has_more"] is True
    hint = result["metadata"]["suggested_next_call"]
    assert hint["tool"] == "list_organizations"
    assert hint["args"]["page"] == 1


# ---------------------------------------------------------------------------
# list_user_api_keys — upstream envelope carries `size` (a real total)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_user_api_keys_surfaces_envelope_size_as_total() -> None:
    payload = {
        "size": 10,
        "results": [{"id": 1, "name": "k1"}, {"id": 2, "name": "k2"}],
    }
    client = StubClient(get_responses={"/users/7/api_keys": [payload]})
    result = await list_user_api_keys(
        cast(AutomoxClient, client), org_id=42, user_id=7, page=0, limit=2
    )

    # Page count under the *_returned name.
    assert result["data"]["keys_returned"] == 2
    # The envelope `size` is the real grand total.
    assert result["data"]["total_keys"] == 10
    pagination = result["metadata"]["pagination"]
    assert pagination["total_elements"] == 10
    # 2 of 10 returned on page 0 with limit 2 => more pages.
    assert pagination["has_more"] is True
    hint = result["metadata"]["suggested_next_call"]
    assert hint["tool"] == "list_user_api_keys"
    assert hint["args"]["page"] == 1


@pytest.mark.asyncio
async def test_list_user_api_keys_no_total_when_envelope_absent() -> None:
    # A bare list (no envelope) supplies no real total.
    client = StubClient(get_responses={"/users/7/api_keys": [[{"id": 1, "name": "k1"}]]})
    result = await list_user_api_keys(cast(AutomoxClient, client), org_id=42, user_id=7)

    assert result["data"]["keys_returned"] == 1
    assert "total_keys" not in result["data"]
    assert "total_elements" not in result["metadata"]["pagination"]


# ---------------------------------------------------------------------------
# list_server_groups
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_server_groups_page_count_is_returned_not_total() -> None:
    client = StubClient(get_responses={"/servergroups": [[_group(1), _group(2)]]})
    result = await list_server_groups(cast(AutomoxClient, client), org_id=555)

    assert result["data"]["groups_returned"] == 2
    assert "total_groups" not in result["data"]
    assert "pagination" in result["metadata"]
    assert "total_elements" not in result["metadata"]["pagination"]


@pytest.mark.asyncio
async def test_list_server_groups_suggests_next_call_on_full_page() -> None:
    client = StubClient(get_responses={"/servergroups": [[_group(1), _group(2)]]})
    result = await list_server_groups(cast(AutomoxClient, client), org_id=555, page=0, limit=2)

    assert result["metadata"]["pagination"]["has_more"] is True
    hint = result["metadata"]["suggested_next_call"]
    assert hint["tool"] == "list_server_groups"
    assert hint["args"]["page"] == 1


# ---------------------------------------------------------------------------
# list_webhooks — cursor-paginated; real total only when upstream supplies one
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_webhooks_page_count_is_returned_without_total() -> None:
    client = StubClient(
        get_responses={f"/organizations/{_ORG_UUID}/webhooks": [{"data": [{"id": "w1"}]}]}
    )
    result = await list_webhooks(cast(AutomoxClient, client), org_uuid=_ORG_UUID)

    assert result["data"]["webhooks_returned"] == 1
    # No upstream total => no grand-total field.
    assert "total_webhooks" not in result["data"]
    assert "pagination" in result["metadata"]


@pytest.mark.asyncio
async def test_list_webhooks_surfaces_upstream_total_when_present() -> None:
    client = StubClient(
        get_responses={
            f"/organizations/{_ORG_UUID}/webhooks": [
                {"data": [{"id": "w1"}], "total": 12, "nextCursor": "abc"}
            ]
        }
    )
    result = await list_webhooks(cast(AutomoxClient, client), org_uuid=_ORG_UUID, limit=1)

    assert result["data"]["webhooks_returned"] == 1
    # Real upstream total surfaced as a grand total.
    assert result["data"]["total_webhooks"] == 12
    pagination = result["metadata"]["pagination"]
    assert pagination["total_elements"] == 12
    # Cursor present => more pages, and the block stays consistent with the data.
    assert pagination["has_more"] is True
    assert pagination["next_cursor"] == "abc"
