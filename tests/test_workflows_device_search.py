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
    get_searchable_fields,
    list_saved_searches,
    list_searches_for_device,
    refresh_saved_search_cache,
    run_saved_search,
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

# NB: this is the FALLBACK (non-Spring) response shape — a `data`/`total`
# envelope. The live `/device/search` endpoint returns a Spring `Page`
# (`content`/`total_elements`); that real shape is exercised by
# test_advanced_search_parses_spring_page_envelope. Keep both: this one
# guards the `extract_list` fallback branch, not the live contract.
_SEARCH_RESULTS = {
    "total": 100,
    "data": [
        {"id": 1, "hostname": "host-1", "os_family": "Windows"},
        {"id": 2, "hostname": "host-2", "os_family": "macOS"},
    ],
}

_DEVICE_DETAIL = {
    # Mirrors the live `/servers/{uuid}` response shape verified against the
    # production tenant on 2026-05-28 — the canonical endpoint uses `name`
    # / `display_name`, not `hostname`. Future drift in the response shape
    # will fail loudly via test_device_by_uuid_returns_detail.
    "id": 123456,
    "uuid": "dev-001",
    "server_group_id": 9876,
    "organization_id": 42,
    "name": "host-1",
    "display_name": "host-1",
    "custom_name": "",
    "os_family": "Windows",
    "os_name": "Microsoft Windows 11 Pro",
    "os_version": "10.0.26100",
    "agent_version": "1.45.48",
    "compliant": True,
    "connected": True,
    "ip_addrs": ["10.0.0.1"],
    "ip_addrs_private": ["10.0.0.1"],
    "last_refresh_time": "2026-05-28T12:00:00+0000",
    "last_logged_in_user": "alice",
    "serial_number": "SN-001",
    "tags": [],
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
        query={"filters": [{"AND": [{"scope": "DEVICE", "field": "name"}]}]},
        page=2,
        limit=25,
    )

    _, _, json_data = client.calls[0]
    # organizationUuids is required in the body (path UUID is not enough);
    # filters merge into the body root (NOT under `query`); page size is `size`.
    assert json_data["organizationUuids"] == [_ORG_UUID]
    assert json_data["filters"] == [{"AND": [{"scope": "DEVICE", "field": "name"}]}]
    assert "query" not in json_data
    assert json_data["page"] == 2
    assert json_data["size"] == 25
    assert "limit" not in json_data


@pytest.mark.asyncio
async def test_advanced_search_parses_spring_page_envelope() -> None:
    """Live search returns a Spring Page (`content`/`total_elements`), not `data`."""
    path = f"/server-groups-api/v1/organizations/{_ORG_UUID}/device/search"
    envelope = {
        "content": [{"id": 1, "name": "host-1"}, {"id": 2, "name": "host-2"}],
        "total_elements": 227,
        "total_pages": 10,
        "number": 0,
        "size": 25,
        "first": True,
        "last": False,
    }
    client = _make_client(post_responses={path: [envelope]})
    result = await advanced_device_search(
        cast(AutomoxClient, client),
        query={"filters": []},
    )

    assert result["data"]["total_devices"] == 227
    assert len(result["data"]["devices"]) == 2
    assert result["metadata"]["pagination"]["has_more"] is True


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

    assert result["data"]["name"] == "host-1"
    assert result["data"]["display_name"] == "host-1"
    assert result["data"]["uuid"] == "dev-001"
    assert result["data"]["agent_version"] == "1.45.48"
    assert result["data"]["compliant"] is True
    assert result["data"]["serial_number"] == "SN-001"
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
    # Upstream needs the spec wrapped in a `search` envelope carrying
    # organizationUuids — a top-level `query` key returns HTTP 500.
    assert body == {
        "name": "All Windows",
        "search": {"os_family": "Windows", "organizationUuids": [_ORG_UUID]},
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
async def test_update_saved_search_name_only_is_read_modify_write() -> None:
    """Name-only update must GET the existing record and re-PUT the full object.

    The upstream PUT is full-replace and 500s on a partial (name-only) body
    (verified live, #132 follow-up), so a partial update must preserve the
    existing `search`.
    """
    path = f"/server-groups-api/v1/organizations/{_ORG_UUID}/device/saved-search/ss-001"
    existing = {
        "id": "ss-001",
        "name": "Old Name",
        "search": {"filters": [{"AND": []}], "size": 25},
    }
    client = _make_client(
        get_responses={path: [existing]},
        put_responses={path: [{"id": "ss-001", "name": "Renamed"}]},
    )
    result = await update_saved_search(
        cast(AutomoxClient, client),
        saved_search_id="ss-001",
        name="Renamed",
    )

    assert client.calls[0][0] == "GET"  # read
    put_method, _, body = client.calls[1]  # modify-write
    assert put_method == "PUT"
    assert body["name"] == "Renamed"  # overlaid
    assert body["search"]["filters"] == [{"AND": []}]  # existing search preserved
    assert body["search"]["size"] == 25
    assert body["search"]["organizationUuids"] == [_ORG_UUID]  # org scoping injected
    assert result["data"]["updated"] is True
    assert result["data"]["saved_search_id"] == "ss-001"


@pytest.mark.asyncio
async def test_update_saved_search_query_rebuilds_search_and_keeps_name() -> None:
    path = f"/server-groups-api/v1/organizations/{_ORG_UUID}/device/saved-search/ss-001"
    existing = {"id": "ss-001", "name": "Keep Me", "search": {"filters": [{"OLD": []}]}}
    client = _make_client(
        get_responses={path: [existing]},
        put_responses={path: [{"id": "ss-001"}]},
    )
    await update_saved_search(
        cast(AutomoxClient, client),
        saved_search_id="ss-001",
        query={"filters": [{"AND": []}]},
    )

    _, _, body = client.calls[1]
    assert body["name"] == "Keep Me"  # name preserved from existing record
    assert body["search"] == {"filters": [{"AND": []}], "organizationUuids": [_ORG_UUID]}
    assert "query" not in body


@pytest.mark.asyncio
async def test_create_saved_search_preserves_caller_org_uuids() -> None:
    """If the caller pre-supplies organizationUuids, we don't clobber them."""
    path = f"/server-groups-api/v1/organizations/{_ORG_UUID}/device/saved-search"
    client = _make_client(post_responses={path: [{"id": "ss-x"}]})
    await create_saved_search(
        cast(AutomoxClient, client),
        name="Cross-org",
        query={"filters": [], "organizationUuids": ["other-org"]},
    )

    _, _, body = client.calls[0]
    assert body["search"]["organizationUuids"] == ["other-org"]


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


# ---------------------------------------------------------------------------
# Search & metadata enrichment (issue #91 category D)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_searchable_fields_passes_grouped_object_through() -> None:
    path = "/server-groups-api/device/metadata/fields"
    grouped = {
        "device": [{"name": "hostname", "type": "string"}],
        "patch": [{"name": "severity", "type": "enum"}],
    }
    client = _make_client(get_responses={path: [grouped]})
    result = await get_searchable_fields(cast(AutomoxClient, client))
    assert result["data"] == grouped
    # distinct endpoint from the flat device-fields metadata
    _, called_path, _ = client.calls[0]
    assert called_path.endswith("/metadata/fields")
    assert not called_path.endswith("device-fields")


@pytest.mark.asyncio
async def test_list_searches_for_device_forwards_type_filter() -> None:
    device = "dev-uuid-9"
    path = f"/server-groups-api/v1/organizations/{_ORG_UUID}/device/saved-search/server/{device}"
    client = _make_client(get_responses={path: [["ss-1", "ss-2"]]})
    result = await list_searches_for_device(
        cast(AutomoxClient, client), device_uuid=device, search_type="dynamic"
    )
    assert result["data"]["device_uuid"] == device
    assert result["data"]["total_searches"] == 2
    _, _path, params = client.calls[0]
    assert params == {"type": "dynamic"}


@pytest.mark.asyncio
async def test_list_searches_for_device_omits_type_when_unset() -> None:
    device = "dev-uuid-9"
    path = f"/server-groups-api/v1/organizations/{_ORG_UUID}/device/saved-search/server/{device}"
    client = _make_client(get_responses={path: [[]]})
    await list_searches_for_device(cast(AutomoxClient, client), device_uuid=device)
    _, _path, params = client.calls[0]
    assert params is None


@pytest.mark.asyncio
async def test_run_saved_search_extracts_page_envelope_and_pagination() -> None:
    search_id = "ss-007"
    path = f"/server-groups-api/v1/organizations/{_ORG_UUID}/device/search/{search_id}"
    page_obj = {
        "content": [{"id": 1, "hostname": "host-a"}, {"id": 2, "hostname": "host-b"}],
        "number": 0,
        "size": 50,
        "totalElements": 2,
        "totalPages": 1,
        "first": True,
        "last": True,
    }
    client = _make_client(get_responses={path: [page_obj]})
    result = await run_saved_search(
        cast(AutomoxClient, client),
        search_id=search_id,
        page=0,
        size=50,
        fields=["hostname"],
    )
    assert result["data"]["total_devices"] == 2
    assert result["data"]["devices"][0]["hostname"] == "host-a"
    assert result["metadata"]["pagination"]["has_more"] is False

    _, _path, params = client.calls[0]
    assert params["page"] == 0
    assert params["size"] == 50
    assert params["fields"] == ["hostname"]


@pytest.mark.asyncio
async def test_refresh_saved_search_cache_posts_and_flags_refreshed() -> None:
    search_id = "ss-007"
    path = f"/server-groups-api/v1/organizations/{_ORG_UUID}/device/search/{search_id}/refresh"
    client = _make_client(post_responses={path: [{}]})
    result = await refresh_saved_search_cache(cast(AutomoxClient, client), search_id=search_id)
    assert result["data"]["search_id"] == search_id
    assert result["data"]["refreshed"] is True
    method, called_path, _ = client.calls[0]
    assert method == "POST"
    assert called_path.endswith("/refresh")
