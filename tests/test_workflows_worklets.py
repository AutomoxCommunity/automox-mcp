"""Tests for worklet catalog workflows."""

from typing import Any, cast

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxClient
from automox_mcp.utils.sanitize import sanitize_dict
from automox_mcp.workflows.worklets import (
    get_worklet_detail,
    search_worklet_catalog,
)

_WORKLET_LIST: list[dict[str, Any]] = [
    # Live /wis/search item shape (sanitized capture 2026-06-05): `uuid`,
    # plural `categories`, trust/availability signals, and NO status field.
    {
        "uuid": "wklt-001",
        "name": "Disable USB Storage",
        "description": "Disables USB mass storage devices",
        "categories": ["Security"],
        "os_family": "Windows",
        "language": "PowerShell",
        "version": "1.2.0",
        # Live /wis/search returns device_type as a LIST (verified 2026-06-05:
        # ['SERVER', 'WORKSTATION']), not a scalar string.
        "device_type": ["SERVER", "WORKSTATION"],
        "verified": True,
        "access": "premium",
        "license_required": False,
        "create_time": "2024-01-15T00:00:00Z",
        "update_time": "2024-06-01T00:00:00Z",
    },
    # Legacy/defensive shape: singular `category`, `id` instead of `uuid`.
    {
        "id": "wklt-002",
        "name": "Check Disk Space",
        "description": "Alerts when disk space is below threshold",
        "category": "Monitoring",
        "os_families": ["Windows", "macOS", "Linux"],
        "author": "Community",
    },
]

# Live /wis/search/{uuid} detail shape (sanitized capture 2026-06-05): `uuid`,
# plural `categories`, `device_type` as a list, the `user_interaction_required`
# safety flag, and the trust/availability signals — NO `status` field.
_WORKLET_DETAIL: dict[str, Any] = {
    "uuid": "wklt-001",
    "name": "Disable USB Storage",
    "description": "Disables USB mass storage devices",
    "categories": ["Security"],
    "os_family": "Windows",
    "device_type": ["SERVER", "WORKSTATION"],
    "language": "PowerShell",
    "version": "1.2.0",
    "verified": True,
    "access": "premium",
    "license_required": False,
    "user_interaction_required": False,
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
    assert usb["categories"] == ["Security"]
    # Trust/availability signals from the live catalog shape are projected.
    assert usb["verified"] is True
    assert usb["access"] == "premium"
    assert usb["license_required"] is False
    assert usb["language"] == "PowerShell"
    assert usb["version"] == "1.2.0"

    disk = next(w for w in result["data"]["worklets"] if w["name"] == "Check Disk Space")
    assert disk["os_families"] == ["Windows", "macOS", "Linux"]
    # Legacy singular `category` falls back into the plural key.
    assert disk["categories"] == "Monitoring"


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
    # Finding 46: the live `user_interaction_required` safety flag is surfaced
    # (was dropped from the projection allowlist). False is a real live value
    # and must round-trip, not be coerced away.
    assert result["data"]["user_interaction_required"] is False
    assert result["data"]["categories"] == ["Security"]
    assert result["data"]["device_type"] == ["SERVER", "WORKSTATION"]


@pytest.mark.asyncio
async def test_detail_code_survives_response_sanitization() -> None:
    """End-to-end (issue #206): a worklet whose code contains corruption-
    triggering syntax — a `[bool](...)` cast and angle-bracket content — survives
    ``sanitize_dict`` (the exact pass ``as_tool_response`` applies to every tool
    response). This proves the ``CODE_BEARING_FIELDS`` exemption fires on the real
    worklet-detail shape, where the code is a value of the ``data`` key. The
    workflow-output assertions above do NOT exercise sanitization, so without this
    test nothing catches a regression that re-mangles code on read-back.
    """
    eval_code = "$x = [bool](Get-NetFirewallRule -DisplayName $n)\nif (-not $x) { exit 1 }"
    rem_code = "Set-Content config.xml '<root><enabled>true</enabled></root>'"
    detail = {**_WORKLET_DETAIL, "evaluation_code": eval_code, "remediation_code": rem_code}
    client = StubClient(get_responses={"/wis/search/wklt-001": [detail]})
    result = await get_worklet_detail(cast(AutomoxClient, client), org_id=42, item_id="wklt-001")

    sanitized = sanitize_dict(result)
    # The cast and the angle-bracket XML must round-trip uncorrupted; a non-code
    # field is still sanitized as a control.
    assert sanitized["data"]["evaluation_code"] == eval_code
    assert sanitized["data"]["remediation_code"] == rem_code


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
