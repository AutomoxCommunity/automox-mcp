"""Tests for worklet catalog workflows."""

from typing import Any, cast

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.worklets import (
    get_worklet_detail,
    search_worklet_catalog,
)

_WORKLET_LIST: list[dict[str, Any]] = [
    {
        "id": "wklt-001",
        "name": "Disable USB Storage",
        "description": "Disables USB mass storage devices",
        "category": "Security",
        "os_family": "Windows",
        "author": "Automox",
        "created_at": "2024-01-15T00:00:00Z",
    },
    {
        "id": "wklt-002",
        "name": "Check Disk Space",
        "description": "Alerts when disk space is below threshold",
        "category": "Monitoring",
        "os_families": ["Windows", "macOS", "Linux"],
        "author": "Community",
    },
]

_WORKLET_DETAIL: dict[str, Any] = {
    "id": "wklt-001",
    "name": "Disable USB Storage",
    "description": "Disables USB mass storage devices",
    "category": "Security",
    "os_family": "Windows",
    "author": "Automox",
    "evaluation_code": "Get-ItemProperty -Path 'HKLM:\\SYSTEM'",
    "remediation_code": "Set-ItemProperty -Path 'HKLM:\\SYSTEM'",
    "notes": "Requires admin privileges",
}


# ---------------------------------------------------------------------------
# search_worklet_catalog
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_returns_summaries() -> None:
    client = StubClient(get_responses={"/wis/search": [_WORKLET_LIST]})
    result = await search_worklet_catalog(cast(AutomoxClient, client), org_id=42)

    assert result["data"]["total_worklets"] == 2
    assert len(result["data"]["worklets"]) == 2


@pytest.mark.asyncio
async def test_search_passes_query() -> None:
    client = StubClient(get_responses={"/wis/search": [[]]})
    await search_worklet_catalog(cast(AutomoxClient, client), org_id=42, query="usb")

    params = client.calls[0][2]
    assert params["q"] == "usb"
    assert params["o"] == 42


@pytest.mark.asyncio
async def test_search_omits_none_query() -> None:
    client = StubClient(get_responses={"/wis/search": [[]]})
    await search_worklet_catalog(cast(AutomoxClient, client), org_id=42)

    params = client.calls[0][2]
    assert "q" not in params


@pytest.mark.asyncio
async def test_search_includes_optional_fields() -> None:
    client = StubClient(get_responses={"/wis/search": [_WORKLET_LIST]})
    result = await search_worklet_catalog(cast(AutomoxClient, client), org_id=42)

    usb = next(w for w in result["data"]["worklets"] if w["name"] == "Disable USB Storage")
    assert usb["os_family"] == "Windows"
    assert usb["author"] == "Automox"

    disk = next(w for w in result["data"]["worklets"] if w["name"] == "Check Disk Space")
    assert disk["os_families"] == ["Windows", "macOS", "Linux"]


@pytest.mark.asyncio
async def test_search_handles_non_list_response() -> None:
    client = StubClient(get_responses={"/wis/search": ["unexpected"]})
    result = await search_worklet_catalog(cast(AutomoxClient, client), org_id=42)
    assert result["data"]["total_worklets"] == 0
    assert result["data"]["worklets"] == []


# ---------------------------------------------------------------------------
# get_worklet_detail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detail_returns_full_info() -> None:
    client = StubClient(get_responses={"/wis/search/wklt-001": [_WORKLET_DETAIL]})
    result = await get_worklet_detail(cast(AutomoxClient, client), org_id=42, item_id="wklt-001")

    assert result["data"]["id"] == "wklt-001"
    assert result["data"]["name"] == "Disable USB Storage"
    assert result["data"]["evaluation_code"] == "Get-ItemProperty -Path 'HKLM:\\SYSTEM'"
    assert result["data"]["remediation_code"] == "Set-ItemProperty -Path 'HKLM:\\SYSTEM'"
    assert result["data"]["notes"] == "Requires admin privileges"


@pytest.mark.asyncio
async def test_detail_handles_non_mapping_response() -> None:
    client = StubClient(get_responses={"/wis/search/bad": ["unexpected"]})
    result = await get_worklet_detail(cast(AutomoxClient, client), org_id=42, item_id="bad")
    assert result["data"]["id"] is None
    assert result["data"]["name"] is None


@pytest.mark.asyncio
async def test_detail_passes_org_id() -> None:
    client = StubClient(get_responses={"/wis/search/wklt-001": [_WORKLET_DETAIL]})
    await get_worklet_detail(cast(AutomoxClient, client), org_id=99, item_id="wklt-001")

    params = client.calls[0][2]
    assert params["o"] == 99


@pytest.mark.asyncio
async def test_search_prefers_uuid_over_id() -> None:
    """The live API uses 'uuid' as the identifier field."""
    worklets = [
        {
            "uuid": "real-uuid-001",
            "id": "old-id-001",
            "name": "Test Worklet",
            "description": "Test",
            "category": "Test",
        },
    ]
    client = StubClient(get_responses={"/wis/search": [worklets]})
    result = await search_worklet_catalog(cast(AutomoxClient, client), org_id=42)

    assert result["data"]["worklets"][0]["id"] == "real-uuid-001"


@pytest.mark.asyncio
async def test_search_falls_back_to_id() -> None:
    """Worklets without 'uuid' fall back to 'id'."""
    worklets = [{"id": "fallback-001", "name": "Old", "description": "Old", "category": "Test"}]
    client = StubClient(get_responses={"/wis/search": [worklets]})
    result = await search_worklet_catalog(cast(AutomoxClient, client), org_id=42)

    assert result["data"]["worklets"][0]["id"] == "fallback-001"


@pytest.mark.asyncio
async def test_search_handles_dict_wrapped_response() -> None:
    """The live API wraps the list in a dict with a 'data' key."""
    wrapped = {"data": [{"uuid": "w-1", "name": "Test", "description": "d", "category": "c"}]}
    client = StubClient(get_responses={"/wis/search": [wrapped]})
    result = await search_worklet_catalog(cast(AutomoxClient, client), org_id=42)

    assert result["data"]["total_worklets"] == 1
    assert result["data"]["worklets"][0]["id"] == "w-1"
