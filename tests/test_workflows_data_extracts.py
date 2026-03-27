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

_EXTRACT_LIST: list[dict[str, Any]] = [
    {
        "id": "ext-001",
        "name": "Device Report Q1",
        "status": "completed",
        "type": "devices",
        "created_at": "2026-01-15T00:00:00Z",
        "file_size": 1024000,
    },
    {
        "id": "ext-002",
        "name": "Patch Report",
        "status": "pending",
        "type": "patches",
    },
]

_EXTRACT_DETAIL: dict[str, Any] = {
    "id": "ext-001",
    "name": "Device Report Q1",
    "status": "completed",
    "type": "devices",
    "created_at": "2026-01-15T00:00:00Z",
    "file_size": 1024000,
    "download_url": "https://example.com/download/ext-001",
    "expires_at": "2026-02-15T00:00:00Z",
    "row_count": 500,
}


# ---------------------------------------------------------------------------
# list_data_extracts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_returns_extracts() -> None:
    client = StubClient(get_responses={"/data-extracts": [_EXTRACT_LIST]})
    result = await list_data_extracts(cast(AutomoxClient, client), org_id=42)

    assert result["data"]["total_extracts"] == 2
    assert len(result["data"]["extracts"]) == 2


@pytest.mark.asyncio
async def test_list_includes_optional_fields() -> None:
    client = StubClient(get_responses={"/data-extracts": [_EXTRACT_LIST]})
    result = await list_data_extracts(cast(AutomoxClient, client), org_id=42)

    q1 = next(e for e in result["data"]["extracts"] if e["id"] == "ext-001")
    assert q1["type"] == "devices"
    assert q1["file_size"] == 1024000


@pytest.mark.asyncio
async def test_list_passes_org_id() -> None:
    client = StubClient(get_responses={"/data-extracts": [[]]})
    await list_data_extracts(cast(AutomoxClient, client), org_id=99)

    params = client.calls[0][2]
    assert params["o"] == 99


@pytest.mark.asyncio
async def test_list_handles_non_list_response() -> None:
    client = StubClient(get_responses={"/data-extracts": ["unexpected"]})
    result = await list_data_extracts(cast(AutomoxClient, client), org_id=42)
    assert result["data"]["total_extracts"] == 0


@pytest.mark.asyncio
async def test_list_handles_single_mapping_response() -> None:
    single = {"id": "ext-001", "name": "Single", "status": "completed"}
    client = StubClient(get_responses={"/data-extracts": [single]})
    result = await list_data_extracts(cast(AutomoxClient, client), org_id=42)
    assert result["data"]["total_extracts"] == 1


# ---------------------------------------------------------------------------
# get_data_extract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_returns_detail() -> None:
    client = StubClient(get_responses={"/data-extracts/ext-001": [_EXTRACT_DETAIL]})
    result = await get_data_extract(cast(AutomoxClient, client), org_id=42, extract_id="ext-001")

    assert result["data"]["id"] == "ext-001"
    assert result["data"]["download_url"] == "https://example.com/download/ext-001"
    assert result["data"]["row_count"] == 500


@pytest.mark.asyncio
async def test_get_handles_non_mapping_response() -> None:
    client = StubClient(get_responses={"/data-extracts/bad": ["unexpected"]})
    result = await get_data_extract(cast(AutomoxClient, client), org_id=42, extract_id="bad")
    assert result["data"]["id"] is None


# ---------------------------------------------------------------------------
# create_data_extract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_submits_request() -> None:
    response = {"id": "ext-003", "name": "New Extract", "status": "pending"}
    client = StubClient(post_responses={"/data-extracts": [response]})
    result = await create_data_extract(
        cast(AutomoxClient, client),
        org_id=42,
        extract_data={"type": "devices"},
    )

    assert result["data"]["id"] == "ext-003"
    assert result["data"]["status"] == "pending"
    assert client.calls[0][0] == "POST"


@pytest.mark.asyncio
async def test_create_handles_empty_response() -> None:
    client = StubClient(post_responses={"/data-extracts": [{}]})
    result = await create_data_extract(
        cast(AutomoxClient, client),
        org_id=42,
        extract_data={"type": "devices"},
    )
    assert result["data"]["status"] == "pending"
    assert result["data"]["message"] == "Data extract request submitted."
