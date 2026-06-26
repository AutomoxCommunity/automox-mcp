"""Regression test for list_saved_searches collapsing a Spring Page.

The `/device/saved-search/list` endpoint returns a Spring `Page` envelope
(`content` + `totalElements`/`last`), not a `data` list. The old wrapper ran
`extract_list` on it, which has no Spring-Page case and fell through to wrapping
the whole envelope as one record; the projection then picked snake_case keys
(`query`/`created_at`) that don't exist on the envelope, so every saved search
rendered as `{}` and the model lost the `id` needed to get/run/delete it.

The DTO field for the filter spec is `search` (the same envelope
`create_saved_search` writes), not `query`. These fixtures use sanitized
real-shape payloads, per the repo testing convention.
"""

from typing import Any, cast

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.device_search import list_saved_searches

_ORG_UUID = "11111111-2222-3333-4444-555555555555"
_LIST_PATH = f"/server-groups-api/v1/organizations/{_ORG_UUID}/device/saved-search/list"

# Spring Page envelope with the real saved-search DTO field names: `search`
# (the filter spec, mirroring create_saved_search's `search` envelope) and
# camelCase timestamps.
_SPRING_PAGE = {
    "content": [
        {
            "id": "ss-001",
            "name": "Stale Devices",
            "description": "Not seen in 30 days",
            "search": {"filters": [{"AND": [{"field": "lastSeen"}]}]},
            "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-01-02T00:00:00Z",
        },
        {
            "id": "ss-002",
            "name": "Windows Servers",
            "search": {"filters": [{"AND": [{"field": "os_family"}]}]},
            "createdAt": "2026-01-03T00:00:00Z",
        },
    ],
    "totalElements": 2,
    "totalPages": 1,
    "number": 0,
    "size": 25,
    "first": True,
    "last": True,
}


def _make_client(**kwargs: Any) -> StubClient:
    client = StubClient(**kwargs)
    client.org_uuid = _ORG_UUID
    return client


@pytest.mark.asyncio
async def test_list_saved_searches_unwraps_spring_page() -> None:
    client = _make_client(get_responses={_LIST_PATH: [_SPRING_PAGE]})
    result = await list_saved_searches(cast(AutomoxClient, client))

    content = cast(list[Any], _SPRING_PAGE["content"])
    saved = result["data"]["saved_searches"]

    # One record per content item — NOT one collapsed envelope record.
    assert len(saved) == len(content)
    # Count reflects totalElements, not the page slice length (here they match,
    # but the field comes from the envelope, not len()).
    assert result["data"]["total_searches"] == _SPRING_PAGE["totalElements"]

    # Each item retains its real fields — id/name/search survive, no `{}`.
    first = saved[0]
    assert first != {}
    assert first["id"] == "ss-001"
    assert first["name"] == "Stale Devices"
    assert first["search"] == {"filters": [{"AND": [{"field": "lastSeen"}]}]}
    assert saved[1]["id"] == "ss-002"

    # Spring envelope fields don't leak into individual records.
    assert "content" not in first
    assert "totalElements" not in first

    # Spring pagination surfaced under metadata.pagination.
    assert result["metadata"]["pagination"]["total_elements"] == 2
    assert result["metadata"]["pagination"]["has_more"] is False


@pytest.mark.asyncio
async def test_list_saved_searches_empty_spring_page() -> None:
    empty_page = {"content": [], "totalElements": 0, "first": True, "last": True}
    client = _make_client(get_responses={_LIST_PATH: [empty_page]})
    result = await list_saved_searches(cast(AutomoxClient, client))

    assert result["data"]["total_searches"] == 0
    assert result["data"]["saved_searches"] == []
