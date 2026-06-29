"""Tests for data extract workflows."""

from typing import Any, cast

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.data_extracts import (
    create_data_extract,
    get_data_extract,
    list_data_extracts,
)

# Sanitized real shapes captured from the 2026-06-05 read-only live probe.
# GET /data-extracts returns a {"results": [...], "size": N} envelope; each item
# has integer id, organization_id, user_id, status (spec enum), is_completed,
# created_at, download_expires_at, download_url (null on expired), type, and a
# parameters {start_time, end_time} window. There is NO name/file_size/row_count/
# updated_at/expires_at key — those were invented by the old fixtures.
_EXTRACT_LIST: dict[str, Any] = {
    "results": [
        {
            "id": 1001,
            "organization_id": 42,
            "user_id": 7,
            "status": "expired",
            "is_completed": False,
            "type": "patch-history",
            "created_at": "2026-01-15T00:00:00Z",
            "download_expires_at": "2026-01-22T00:00:00Z",
            "download_url": None,
            "parameters": {
                "start_time": "2026-01-01T00:00:00Z",
                "end_time": "2026-01-15T00:00:00Z",
            },
        },
        {
            "id": 1002,
            "organization_id": 42,
            "user_id": 7,
            "status": "complete",
            "is_completed": True,
            "type": "api-activity",
            "created_at": "2026-02-01T00:00:00Z",
            "download_expires_at": "2026-02-08T00:00:00Z",
            "download_url": "https://example.com/download/1002?sig=redacted",
            "parameters": {
                "start_time": "2026-01-15T00:00:00Z",
                "end_time": "2026-02-01T00:00:00Z",
            },
        },
    ],
    "size": 2,
}

# Expired detail: download_url null (the true cannot-download signal), even
# though download_expires_at carries a value.
_EXTRACT_DETAIL: dict[str, Any] = {
    "id": 1001,
    "organization_id": 42,
    "user_id": 7,
    "status": "expired",
    "is_completed": False,
    "type": "patch-history",
    "created_at": "2026-01-15T00:00:00Z",
    "download_expires_at": "2026-01-22T00:00:00Z",
    "download_url": None,
    "parameters": {
        "start_time": "2026-01-01T00:00:00Z",
        "end_time": "2026-01-15T00:00:00Z",
    },
}

# Complete detail with a live download link present.
_EXTRACT_DETAIL_COMPLETE: dict[str, Any] = {
    "id": 1002,
    "status": "complete",
    "is_completed": True,
    "type": "api-activity",
    "created_at": "2026-02-01T00:00:00Z",
    "download_expires_at": "2026-02-08T00:00:00Z",
    "download_url": "https://example.com/download/1002?sig=redacted",
}


# ---------------------------------------------------------------------------
# list_data_extracts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_unwraps_envelope() -> None:
    # Load-bearing ordering: the {results, size} envelope must be unwrapped
    # BEFORE the single-row wrap, so total comes from size (or len(results)),
    # never 1 for the whole envelope dict.
    client = StubClient(get_responses={"/data-extracts": [_EXTRACT_LIST]})
    result = await list_data_extracts(cast(AutomoxClient, client), org_id=42)

    assert result["data"]["total_extracts"] == 2
    assert len(result["data"]["extracts"]) == 2


@pytest.mark.asyncio
async def test_list_total_from_size_when_results_paginated() -> None:
    # size reflects the full count even when results is a single page.
    envelope = {"results": _EXTRACT_LIST["results"], "size": 35}
    client = StubClient(get_responses={"/data-extracts": [envelope]})
    result = await list_data_extracts(cast(AutomoxClient, client), org_id=42)

    assert result["data"]["total_extracts"] == 35
    assert len(result["data"]["extracts"]) == 2


@pytest.mark.asyncio
async def test_list_surfaces_real_fields_and_drops_phantoms() -> None:
    client = StubClient(get_responses={"/data-extracts": [_EXTRACT_LIST]})
    result = await list_data_extracts(cast(AutomoxClient, client), org_id=42)

    expired = next(e for e in result["data"]["extracts"] if e["id"] == 1001)
    assert expired["type"] == "patch-history"
    assert expired["is_completed"] is False
    assert expired["download_expires_at"] == "2026-01-22T00:00:00Z"
    assert expired["parameters"]["start_time"] == "2026-01-01T00:00:00Z"
    # Phantom keys must be gone.
    assert "name" not in expired
    assert "file_size" not in expired
    # download_url is null on the expired record -> no has_download_url flag.
    assert "has_download_url" not in expired

    complete = next(e for e in result["data"]["extracts"] if e["id"] == 1002)
    assert complete["has_download_url"] is True
    assert "download_url" not in complete


@pytest.mark.asyncio
async def test_list_passes_org_id() -> None:
    client = StubClient(get_responses={"/data-extracts": [{"results": [], "size": 0}]})
    await list_data_extracts(cast(AutomoxClient, client), org_id=99)

    params = client.calls[0][2]
    assert params["o"] == 99


@pytest.mark.asyncio
async def test_list_empty_envelope_results() -> None:
    client = StubClient(get_responses={"/data-extracts": [{"results": [], "size": 0}]})
    result = await list_data_extracts(cast(AutomoxClient, client), org_id=42)
    assert result["data"]["total_extracts"] == 0
    assert result["data"]["extracts"] == []


@pytest.mark.asyncio
async def test_list_handles_non_list_response() -> None:
    client = StubClient(get_responses={"/data-extracts": ["unexpected"]})
    result = await list_data_extracts(cast(AutomoxClient, client), org_id=42)
    # No envelope `size` -> per-page count under `extracts_returned`, not a
    # mislabelled grand total.
    assert result["data"]["extracts_returned"] == 0


@pytest.mark.asyncio
async def test_list_handles_bare_list_fallback() -> None:
    # Resilience: if the API ever returns a bare list, still unwrap per item.
    # A bare list has no upstream grand total, so the page count is reported
    # under `extracts_returned` (not `total_extracts`).
    client = StubClient(get_responses={"/data-extracts": [_EXTRACT_LIST["results"]]})
    result = await list_data_extracts(cast(AutomoxClient, client), org_id=42)
    assert result["data"]["extracts_returned"] == 2


# ---------------------------------------------------------------------------
# get_data_extract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_returns_detail_expired() -> None:
    client = StubClient(get_responses={"/data-extracts/1001": [_EXTRACT_DETAIL]})
    result = await get_data_extract(cast(AutomoxClient, client), org_id=42, extract_id="1001")
    data = result["data"]

    assert data["id"] == 1001
    assert data["status"] == "expired"
    assert data["is_completed"] is False
    # Real link-expiry key populates under its true name.
    assert data["download_expires_at"] == "2026-01-22T00:00:00Z"
    # Phantom keys must be absent.
    assert "expires_at" not in data
    assert "file_size" not in data
    assert "row_count" not in data
    assert "name" not in data
    # Expired record: download_url is null -> has_download_url is NOT set.
    assert "has_download_url" not in data
    # V-155: presigned URL never exposed.
    assert "download_url" not in data


@pytest.mark.asyncio
async def test_get_returns_detail_complete_has_download() -> None:
    client = StubClient(get_responses={"/data-extracts/1002": [_EXTRACT_DETAIL_COMPLETE]})
    result = await get_data_extract(cast(AutomoxClient, client), org_id=42, extract_id="1002")
    data = result["data"]

    assert data["is_completed"] is True
    assert data["has_download_url"] is True
    assert "download_url" not in data


@pytest.mark.asyncio
async def test_get_includes_field_notes_legend() -> None:
    client = StubClient(get_responses={"/data-extracts/1001": [_EXTRACT_DETAIL]})
    result = await get_data_extract(cast(AutomoxClient, client), org_id=42, extract_id="1001")
    notes = result["metadata"]["field_notes"]
    assert set(notes) == {"status", "is_completed", "download_expires_at"}


@pytest.mark.asyncio
async def test_get_handles_non_mapping_response() -> None:
    client = StubClient(get_responses={"/data-extracts/bad": ["unexpected"]})
    result = await get_data_extract(cast(AutomoxClient, client), org_id=42, extract_id="bad")
    assert result["data"]["id"] is None


# ---------------------------------------------------------------------------
# create_data_extract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_reads_array_response() -> None:
    # POST /data-extracts returns an ARRAY of DataExtract (per spec); the created
    # job is element [0]. Fields must be read from that element, not the array.
    response = [{"id": 1003, "status": "queued", "is_completed": False}]
    client = StubClient(post_responses={"/data-extracts": [response]})
    result = await create_data_extract(
        cast(AutomoxClient, client),
        org_id=42,
        extract_data={"type": "patch-history"},
    )

    assert result["data"]["id"] == 1003
    assert result["data"]["status"] == "queued"
    assert result["data"]["is_completed"] is False
    assert client.calls[0][0] == "POST"


@pytest.mark.asyncio
async def test_create_handles_single_mapping_response() -> None:
    response = {"id": 1004, "status": "queued"}
    client = StubClient(post_responses={"/data-extracts": [response]})
    result = await create_data_extract(
        cast(AutomoxClient, client),
        org_id=42,
        extract_data={"type": "api-activity"},
    )
    assert result["data"]["id"] == 1004
    assert result["data"]["status"] == "queued"


@pytest.mark.asyncio
async def test_create_empty_response_no_pending_default() -> None:
    # Empty/[] response must yield id=None and status=None — NOT the out-of-enum
    # "pending" the old code invented.
    client = StubClient(post_responses={"/data-extracts": [[]]})
    result = await create_data_extract(
        cast(AutomoxClient, client),
        org_id=42,
        extract_data={"type": "patch-history"},
    )
    assert result["data"]["id"] is None
    assert result["data"]["status"] is None
    assert result["data"]["message"] == "Data extract request submitted."


@pytest.mark.asyncio
async def test_create_empty_mapping_no_pending_default() -> None:
    client = StubClient(post_responses={"/data-extracts": [{}]})
    result = await create_data_extract(
        cast(AutomoxClient, client),
        org_id=42,
        extract_data={"type": "patch-history"},
    )
    assert result["data"]["status"] is None
    assert result["data"]["message"] == "Data extract request submitted."
