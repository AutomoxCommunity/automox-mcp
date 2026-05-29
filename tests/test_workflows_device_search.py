"""Tests for advanced device search workflows (Server Groups API v2)."""

from typing import Any, cast

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.device_search import (
    advanced_device_search,
    assign_policies_to_saved_search,
    create_saved_search,
    delete_saved_search,
    device_search_typeahead,
    get_cached_search_results,
    get_device_assignments,
    get_device_by_uuid,
    get_device_metadata_fields,
    get_saved_search,
    get_saved_search_results,
    get_search_scopes,
    list_saved_searches,
    update_saved_search,
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
    "id": 123456,
    "uuid": "dev-001",
    "server_group_id": 9876,
    "organization_id": 42,
    "hostname": "host-1",
    "os_family": "Windows",
    "os_name": "Microsoft Windows 11 Pro",
    "os_version": "10.0.26100",
    "agent_version": "1.45.48",
    "compliant": True,
    "ip_addrs": ["10.0.0.1"],
    "ip_addrs_private": ["10.0.0.1"],
    "last_refresh_time": "2026-05-28T12:00:00Z",
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


@pytest.mark.asyncio
async def test_assignments_normalizes_spring_page_envelope() -> None:
    """The upstream API returns a Spring `Page<T>` envelope (`content`,
    `pageable`, `total_elements`, `number_of_elements`...). Earlier
    revisions leaked the Spring fields into the response by wrapping
    the entire envelope as a single record. The wrapper now extracts
    `content` and re-emits pagination data under metadata.pagination.

    Bug #6 from issue #43.
    """
    path = f"/server-groups-api/v1/organizations/{_ORG_UUID}/assignments"
    spring_envelope = {
        "content": [
            {"device_uuid": "dev-1", "policy_id": 1, "group_id": 10},
            {"device_uuid": "dev-2", "policy_id": 2, "group_id": 20},
        ],
        "pageable": {
            "page_number": 0,
            "page_size": 25,
            "offset": 0,
            "sort": {"empty": False, "sorted": True, "unsorted": False},
            "paged": True,
            "unpaged": False,
        },
        "total_elements": 2,
        "total_pages": 1,
        "number_of_elements": 2,
        "size": 25,
        "number": 0,
        "first": True,
        "last": True,
        "empty": False,
        "sort": {"empty": False, "sorted": True, "unsorted": False},
    }
    client = _make_client(get_responses={path: [spring_envelope]})
    result = await get_device_assignments(cast(AutomoxClient, client))

    # Spring fields must NOT leak into data.assignments
    assert result["data"]["total_assignments"] == 2
    first = result["data"]["assignments"][0]
    assert first["device_uuid"] == "dev-1"
    assert "pageable" not in first
    assert "total_elements" not in first
    assert "number_of_elements" not in first

    pagination = result["metadata"]["pagination"]
    assert pagination["page"] == 0
    assert pagination["page_size"] == 25
    assert pagination["total_elements"] == 2
    assert pagination["total_pages"] == 1
    assert pagination["page_number"] == 0
    # Spring's verbose `pageable.paged`/`pageable.unpaged` markers are not surfaced
    assert "paged" not in pagination
    assert "unpaged" not in pagination


@pytest.mark.asyncio
async def test_assignments_handles_empty_spring_page() -> None:
    """An empty Spring page (content=[]) should produce an empty list,
    not leak the Spring envelope as a single record."""
    path = f"/server-groups-api/v1/organizations/{_ORG_UUID}/assignments"
    spring_envelope = {
        "content": [],
        "pageable": {"page_number": 0, "page_size": 25},
        "total_elements": 0,
        "total_pages": 0,
        "number_of_elements": 0,
        "first": True,
        "last": True,
        "empty": True,
    }
    client = _make_client(get_responses={path: [spring_envelope]})
    result = await get_device_assignments(cast(AutomoxClient, client))
    assert result["data"]["total_assignments"] == 0
    assert result["data"]["assignments"] == []


# ---------------------------------------------------------------------------
# get_device_by_uuid
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_device_by_uuid_returns_detail() -> None:
    # Fix for #92: canonical `/servers/{id}` endpoint, with the live tenant
    # accepting a UUID where the spec types `id` as int.
    path = "/servers/dev-001"
    client = _make_client(get_responses={path: [_DEVICE_DETAIL]})
    result = await get_device_by_uuid(
        cast(AutomoxClient, client),
        device_uuid="dev-001",
    )

    assert result["data"]["hostname"] == "host-1"
    assert result["data"]["uuid"] == "dev-001"
    assert result["data"]["agent_version"] == "1.45.48"
    assert result["data"]["compliant"] is True
    # Verify the org_id was passed as the `o` query param (required by /servers/{id}).
    method, called_path, params = client.calls[-1]
    assert method == "GET"
    assert called_path == "/servers/dev-001"
    assert params == {"o": 42, "includeDetails": 1}


@pytest.mark.asyncio
async def test_device_by_uuid_handles_non_mapping() -> None:
    path = "/servers/bad"
    client = _make_client(get_responses={path: ["unexpected"]})
    result = await get_device_by_uuid(
        cast(AutomoxClient, client),
        device_uuid="bad",
    )
    assert result["data"] == {}


# ---------------------------------------------------------------------------
# Saved-search CRUD + bulk-assignment (Device Explorer, 2025-12-11)
# ---------------------------------------------------------------------------


_SAVED_SEARCH_DETAIL = {
    "id": "ss-001",
    "name": "Stale Devices",
    "description": "Not seen in 30 days",
    "query": {"lastSeen": "<30d"},
    "created_at": "2026-01-01T00:00:00Z",
}

_SAVED_SEARCH_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


@pytest.mark.asyncio
async def test_get_saved_search_returns_detail() -> None:
    path = f"/server-groups-api/v1/organizations/{_ORG_UUID}/device/saved-search/ss-001"
    client = _make_client(get_responses={path: [_SAVED_SEARCH_DETAIL]})
    result = await get_saved_search(cast(AutomoxClient, client), saved_search_id="ss-001")
    assert result["data"]["name"] == "Stale Devices"
    assert result["data"]["query"] == {"lastSeen": "<30d"}


@pytest.mark.asyncio
async def test_get_saved_search_handles_non_mapping() -> None:
    path = f"/server-groups-api/v1/organizations/{_ORG_UUID}/device/saved-search/ss-bad"
    client = _make_client(get_responses={path: [["unexpected"]]})
    result = await get_saved_search(cast(AutomoxClient, client), saved_search_id="ss-bad")
    assert result["data"] == {}


@pytest.mark.asyncio
async def test_create_saved_search_posts_body() -> None:
    path = f"/server-groups-api/v1/organizations/{_ORG_UUID}/device/saved-search"
    client = _make_client(post_responses={path: [{"id": "ss-new", "name": "All Windows"}]})
    result = await create_saved_search(
        cast(AutomoxClient, client),
        name="All Windows",
        query={"os_family": "Windows"},
        description="Windows devices",
    )

    method, called_path, body = client.calls[0]
    assert method == "POST"
    assert called_path == path
    assert body == {
        "name": "All Windows",
        "query": {"os_family": "Windows"},
        "description": "Windows devices",
    }
    assert result["data"]["id"] == "ss-new"
    assert result["data"]["created"] is True


@pytest.mark.asyncio
async def test_create_saved_search_omits_description_when_none() -> None:
    path = f"/server-groups-api/v1/organizations/{_ORG_UUID}/device/saved-search"
    client = _make_client(post_responses={path: [{"id": "ss-new"}]})
    await create_saved_search(
        cast(AutomoxClient, client),
        name="Minimal",
        query={"hostname": "host-*"},
    )

    _, _, body = client.calls[0]
    assert "description" not in body
    assert body["name"] == "Minimal"


@pytest.mark.asyncio
async def test_update_saved_search_sends_partial_body() -> None:
    path = f"/server-groups-api/v1/organizations/{_ORG_UUID}/device/saved-search/ss-001"
    client = _make_client(put_responses={path: [{"id": "ss-001", "name": "Renamed"}]})
    result = await update_saved_search(
        cast(AutomoxClient, client),
        saved_search_id="ss-001",
        name="Renamed",
    )

    method, _, body = client.calls[0]
    assert method == "PUT"
    assert body == {"name": "Renamed"}
    assert result["data"]["updated"] is True
    assert result["data"]["saved_search_id"] == "ss-001"


@pytest.mark.asyncio
async def test_delete_saved_search_calls_delete() -> None:
    path = f"/server-groups-api/v1/organizations/{_ORG_UUID}/device/saved-search/ss-001"
    client = _make_client(delete_responses={path: [None]})
    result = await delete_saved_search(cast(AutomoxClient, client), saved_search_id="ss-001")

    method, called_path, _ = client.calls[0]
    assert method == "DELETE"
    assert called_path == path
    assert result["data"] == {"saved_search_id": "ss-001", "deleted": True}


@pytest.mark.asyncio
async def test_get_saved_search_results_returns_devices() -> None:
    path = f"/server-groups-api/v1/organizations/{_ORG_UUID}/device/saved-search/ss-001/results"
    client = _make_client(get_responses={path: [_SEARCH_RESULTS]})
    result = await get_saved_search_results(
        cast(AutomoxClient, client),
        saved_search_id="ss-001",
        page=1,
        limit=25,
    )

    assert result["data"]["total_devices"] == 100
    assert len(result["data"]["devices"]) == 2
    assert result["data"]["saved_search_id"] == "ss-001"
    _, _, params = client.calls[0]
    assert params == {"page": 1, "limit": 25}


@pytest.mark.asyncio
async def test_get_cached_search_results_returns_devices() -> None:
    path = f"/server-groups-api/v1/organizations/{_ORG_UUID}/device/search/run-42/saved"
    client = _make_client(get_responses={path: [_SEARCH_RESULTS]})
    result = await get_cached_search_results(
        cast(AutomoxClient, client),
        search_id="run-42",
    )

    assert result["data"]["search_id"] == "run-42"
    assert result["data"]["total_devices"] == 100


@pytest.mark.asyncio
async def test_assign_policies_to_saved_search_posts_policy_ids() -> None:
    path = f"/server-groups-api/v1/organizations/{_ORG_UUID}/saved-searches/{_SAVED_SEARCH_UUID}"
    client = _make_client(post_responses={path: [{"status": "queued"}]})
    result = await assign_policies_to_saved_search(
        cast(AutomoxClient, client),
        saved_search_uuid=_SAVED_SEARCH_UUID,
        policy_ids=[101, 202],
    )

    method, called_path, body = client.calls[0]
    assert method == "POST"
    assert called_path == path
    assert body == {"policy_ids": [101, 202]}
    assert result["data"]["assigned"] is True
    assert result["data"]["saved_search_uuid"] == _SAVED_SEARCH_UUID
    assert result["data"]["policy_ids"] == [101, 202]


@pytest.mark.asyncio
async def test_get_search_scopes_returns_metadata() -> None:
    path = "/server-groups-api/device/metadata/scopes"
    scopes = [{"name": "device"}, {"name": "group"}, {"name": "org"}]
    client = _make_client(get_responses={path: [scopes]})
    result = await get_search_scopes(cast(AutomoxClient, client))

    assert result["data"]["total_scopes"] == 3
    assert result["data"]["scopes"] == scopes
