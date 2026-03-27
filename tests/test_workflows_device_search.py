"""Tests for advanced device search workflows (Server Groups API v2)."""

from typing import Any, cast

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.device_search import (
    advanced_device_search,
    device_search_typeahead,
    get_device_assignments,
    get_device_by_uuid,
    get_device_metadata_fields,
    list_saved_searches,
)

_ORG_UUID = "11111111-2222-3333-4444-555555555555"

_SAVED_SEARCHES = [
    {
        "id": "ss-001",
        "name": "Stale Devices",
        "description": "Not seen in 30 days",
        "query": {"lastSeen": "<30d"},
    },
    {"id": "ss-002", "name": "Windows Servers", "query": {"os_family": "Windows"}},
]

_SEARCH_RESULTS = {
    "total": 100,
    "data": [
        {"id": 1, "hostname": "host-1", "os_family": "Windows"},
        {"id": 2, "hostname": "host-2", "os_family": "macOS"},
    ],
}

_DEVICE_DETAIL = {
    "uuid": "dev-001",
    "hostname": "host-1",
    "os_family": "Windows",
    "ip_addrs": ["10.0.0.1"],
}

_METADATA_FIELDS = [
    {"name": "hostname", "type": "string"},
    {"name": "os_family", "type": "string"},
    {"name": "last_seen", "type": "datetime"},
]


def _make_client(**kwargs: Any) -> StubClient:
    client = StubClient(**kwargs)
    client.org_uuid = _ORG_UUID
    return client


# ---------------------------------------------------------------------------
# list_saved_searches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_saved_searches_returns_results() -> None:
    path = f"/server-groups-api/v1/organizations/{_ORG_UUID}/device/saved-search/list"
    client = _make_client(get_responses={path: [_SAVED_SEARCHES]})
    result = await list_saved_searches(cast(AutomoxClient, client))

    assert result["data"]["total_searches"] == 2
    assert result["data"]["saved_searches"][0]["name"] == "Stale Devices"


@pytest.mark.asyncio
async def test_list_saved_searches_empty() -> None:
    path = f"/server-groups-api/v1/organizations/{_ORG_UUID}/device/saved-search/list"
    client = _make_client(get_responses={path: [[]]})
    result = await list_saved_searches(cast(AutomoxClient, client))
    assert result["data"]["total_searches"] == 0


# ---------------------------------------------------------------------------
# advanced_device_search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_advanced_search_returns_devices() -> None:
    path = f"/server-groups-api/v1/organizations/{_ORG_UUID}/device/search"
    client = _make_client(post_responses={path: [_SEARCH_RESULTS]})
    result = await advanced_device_search(
        cast(AutomoxClient, client),
        query={"os_family": "Windows"},
    )

    assert result["data"]["total_devices"] == 100
    assert len(result["data"]["devices"]) == 2


@pytest.mark.asyncio
async def test_advanced_search_passes_body() -> None:
    path = f"/server-groups-api/v1/organizations/{_ORG_UUID}/device/search"
    client = _make_client(post_responses={path: [{"data": []}]})
    await advanced_device_search(
        cast(AutomoxClient, client),
        query={"hostname": "test*"},
        page=2,
        limit=25,
    )

    _, _, json_data = client.calls[0]
    assert json_data["query"] == {"hostname": "test*"}
    assert json_data["page"] == 2
    assert json_data["limit"] == 25


# ---------------------------------------------------------------------------
# device_search_typeahead
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_typeahead_returns_suggestions() -> None:
    path = f"/server-groups-api/v1/organizations/{_ORG_UUID}/search/typeahead"
    suggestions = ["Windows 10", "Windows 11", "Windows Server 2022"]
    client = _make_client(post_responses={path: [{"suggestions": suggestions}]})
    result = await device_search_typeahead(
        cast(AutomoxClient, client),
        field="os_name",
        prefix="Wind",
    )

    assert result["data"]["total_suggestions"] == 3
    assert result["data"]["field"] == "os_name"
    assert result["data"]["prefix"] == "Wind"


@pytest.mark.asyncio
async def test_typeahead_handles_list_response() -> None:
    path = f"/server-groups-api/v1/organizations/{_ORG_UUID}/search/typeahead"
    client = _make_client(post_responses={path: [["val1", "val2"]]})
    result = await device_search_typeahead(
        cast(AutomoxClient, client),
        field="hostname",
        prefix="host",
    )
    assert result["data"]["total_suggestions"] == 2


# ---------------------------------------------------------------------------
# get_device_metadata_fields (no org in path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_metadata_fields_returns_fields() -> None:
    path = "/server-groups-api/device/metadata/device-fields"
    client = _make_client(get_responses={path: [_METADATA_FIELDS]})
    result = await get_device_metadata_fields(cast(AutomoxClient, client))

    assert result["data"]["total_fields"] == 3


# ---------------------------------------------------------------------------
# get_device_assignments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assignments_returns_data() -> None:
    path = f"/server-groups-api/v1/organizations/{_ORG_UUID}/assignments"
    assignments = [
        {"device_uuid": "dev-001", "policy_id": 1, "group_id": 10},
    ]
    client = _make_client(get_responses={path: [assignments]})
    result = await get_device_assignments(cast(AutomoxClient, client))

    assert result["data"]["total_assignments"] == 1


# ---------------------------------------------------------------------------
# get_device_by_uuid
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_device_by_uuid_returns_detail() -> None:
    path = f"/server-groups-api/v1/organizations/{_ORG_UUID}/server/dev-001"
    client = _make_client(get_responses={path: [_DEVICE_DETAIL]})
    result = await get_device_by_uuid(
        cast(AutomoxClient, client),
        device_uuid="dev-001",
    )

    assert result["data"]["hostname"] == "host-1"
    assert result["data"]["uuid"] == "dev-001"


@pytest.mark.asyncio
async def test_device_by_uuid_handles_non_mapping() -> None:
    path = f"/server-groups-api/v1/organizations/{_ORG_UUID}/server/bad"
    client = _make_client(get_responses={path: ["unexpected"]})
    result = await get_device_by_uuid(
        cast(AutomoxClient, client),
        device_uuid="bad",
    )
    assert result["data"] == {}
