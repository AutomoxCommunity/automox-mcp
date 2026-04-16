"""Tests for report workflows in automox_mcp.workflows.reports."""

from __future__ import annotations

from typing import Any, cast

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxAPIError, AutomoxClient
from automox_mcp.workflows.reports import (
    _extract_devices,
    _highest_patch_severity,
    get_noncompliant_report,
    get_prepatch_report,
)

# ===========================================================================
# _highest_patch_severity
# ===========================================================================


def test_highest_patch_severity_empty_returns_unknown() -> None:
    assert _highest_patch_severity([]) == "unknown"
    assert _highest_patch_severity(None) == "unknown"


def test_highest_patch_severity_mapping_input() -> None:
    """When patches is a Mapping, values are iterated."""
    patches = {
        "patch1": {"severity": "low"},
        "patch2": {"severity": "critical"},
        "patch3": {"severity": "medium"},
    }
    assert _highest_patch_severity(patches) == "critical"


def test_highest_patch_severity_sequence_input() -> None:
    patches = [
        {"severity": "low"},
        {"severity": "high"},
    ]
    assert _highest_patch_severity(patches) == "high"


def test_highest_patch_severity_cve_severity_fallback() -> None:
    """Falls back to 'cve_severity' when 'severity' is absent."""
    patches = [{"cve_severity": "medium"}]
    assert _highest_patch_severity(patches) == "medium"


def test_highest_patch_severity_non_mapping_items_skipped() -> None:
    """Non-Mapping items inside the sequence are skipped gracefully."""
    patches = ["not-a-dict", {"severity": "low"}]
    assert _highest_patch_severity(patches) == "low"


def test_highest_patch_severity_all_unknown_severities() -> None:
    """When no recognizable severity is found, returns 'unknown'."""
    patches = [{"severity": "banana"}, {"severity": ""}]
    assert _highest_patch_severity(patches) == "unknown"


def test_highest_patch_severity_scalar_returns_unknown() -> None:
    """A scalar (non-sequence, non-mapping) value returns 'unknown'."""
    assert _highest_patch_severity("string-value") == "unknown"
    assert _highest_patch_severity(42) == "unknown"


def test_highest_patch_severity_none_severity_field() -> None:
    """Patch with severity=None falls through to unknown rank."""
    patches = [{"severity": None}, {"severity": "low"}]
    assert _highest_patch_severity(patches) == "low"


# ===========================================================================
# _extract_devices
# ===========================================================================


def test_extract_devices_nested_mapping() -> None:
    response = {"prepatch": {"devices": [{"id": 1}, {"id": 2}]}}
    result = _extract_devices(response, "prepatch", "devices")
    assert result == [{"id": 1}, {"id": 2}]


def test_extract_devices_wrapped_in_list() -> None:
    """API may return a list wrapping the real response dict."""
    response = [{"prepatch": {"devices": [{"id": 10}]}}]
    result = _extract_devices(response, "prepatch", "devices")
    assert result == [{"id": 10}]


def test_extract_devices_missing_key_returns_empty() -> None:
    response = {"prepatch": {}}  # no "devices" key
    result = _extract_devices(response, "prepatch", "devices")
    assert result == []


def test_extract_devices_non_mapping_mid_chain_returns_empty() -> None:
    response = {"prepatch": "not-a-mapping"}
    result = _extract_devices(response, "prepatch", "devices")
    assert result == []


def test_extract_devices_empty_list_returns_empty() -> None:
    result = _extract_devices([], "prepatch", "devices")
    assert result == []


def test_extract_devices_non_sequence_leaf_returns_empty() -> None:
    response = {"nonCompliant": {"devices": 42}}  # int, not a list
    result = _extract_devices(response, "nonCompliant", "devices")
    assert result == []


# ===========================================================================
# get_prepatch_report
# ===========================================================================


def _make_prepatch_response(
    devices: list[dict[str, Any]],
    total: int = 0,
) -> dict[str, Any]:
    return {
        "prepatch": {
            "total": total or len(devices),
            "devices": devices,
        }
    }


@pytest.mark.asyncio
async def test_get_prepatch_report_single_page_explicit_limit() -> None:
    """Explicit limit triggers single-page mode — only one GET call."""
    device = {
        "id": 1,
        "name": "host1",
        "group": "Default",
        "os_family": "Windows",
        "connected": True,
        "compliant": False,
        "needsReboot": False,
        "patches": [{"severity": "high"}, {"severity": "low"}],
    }
    client = StubClient(
        get_responses={"/reports/prepatch": [_make_prepatch_response([device], total=1)]},
    )

    result = await get_prepatch_report(
        cast(AutomoxClient, client),
        org_id=42,
        limit=100,
    )

    assert result["data"]["total_devices"] == 1
    devices = result["data"]["devices"]
    assert len(devices) == 1
    assert devices[0]["server_name"] == "host1"
    assert devices[0]["highest_severity"] == "high"
    assert devices[0]["pending_patches"] == 2

    get_calls = [c for c in client.calls if c[0] == "GET"]
    assert len(get_calls) == 1


@pytest.mark.asyncio
async def test_get_prepatch_report_auto_pagination() -> None:
    """When total > page results, auto-pagination issues multiple GETs."""
    page1_devices = [{"id": i, "name": f"host{i}", "patches": []} for i in range(1, 4)]
    page2_devices = [{"id": 4, "name": "host4", "patches": []}]

    # First page reports total=4 so the loop continues for page 2.
    page1_response = {"prepatch": {"total": 4, "devices": page1_devices}}
    page2_response = {"prepatch": {"total": 4, "devices": page2_devices}}

    client = StubClient(
        get_responses={"/reports/prepatch": [page1_response, page2_response]},
    )

    result = await get_prepatch_report(
        cast(AutomoxClient, client),
        org_id=42,
    )

    assert result["data"]["total_devices"] == 4
    get_calls = [c for c in client.calls if c[0] == "GET"]
    assert len(get_calls) == 2

    # Second request should have an incremented offset
    second_params = get_calls[1][2]
    assert second_params is not None
    assert second_params["offset"] > 0


@pytest.mark.asyncio
async def test_get_prepatch_report_patches_as_mapping() -> None:
    """Patches can come as a Mapping (dict keyed by patch ID)."""
    device = {
        "id": 5,
        "name": "map-host",
        "patches": {
            "KB1234": {"severity": "critical"},
            "KB5678": {"severity": "medium"},
        },
    }
    client = StubClient(
        get_responses={"/reports/prepatch": [_make_prepatch_response([device])]},
    )

    result = await get_prepatch_report(
        cast(AutomoxClient, client),
        org_id=42,
        limit=100,
    )

    devices = result["data"]["devices"]
    assert devices[0]["pending_patches"] == 2
    assert devices[0]["highest_severity"] == "critical"


@pytest.mark.asyncio
async def test_get_prepatch_report_severity_counters() -> None:
    """Summary includes per-severity device counts."""
    devices = [
        {"id": 1, "name": "a", "patches": [{"severity": "critical"}]},
        {"id": 2, "name": "b", "patches": [{"severity": "high"}]},
        {"id": 3, "name": "c", "patches": []},
    ]
    client = StubClient(
        get_responses={"/reports/prepatch": [_make_prepatch_response(devices, total=3)]},
    )

    result = await get_prepatch_report(
        cast(AutomoxClient, client),
        org_id=42,
        limit=500,
    )

    summary = result["data"]["summary"]
    assert summary["critical"] == 1
    assert summary["high"] == 1
    # empty patches → "unknown" severity
    assert summary["unknown"] == 1


@pytest.mark.asyncio
async def test_get_prepatch_report_with_group_id() -> None:
    """group_id parameter is forwarded as 'groupId' in the API request."""
    client = StubClient(
        get_responses={"/reports/prepatch": [_make_prepatch_response([])]},
    )

    await get_prepatch_report(
        cast(AutomoxClient, client),
        org_id=42,
        group_id=7,
        limit=10,
    )

    params = client.calls[0][2]
    assert params is not None
    assert params["groupId"] == 7


@pytest.mark.asyncio
async def test_get_prepatch_report_stops_when_page_empty() -> None:
    """Pagination stops early when a page returns no devices (avoids infinite loop)."""
    page1 = {"prepatch": {"total": 100, "devices": [{"id": 1, "name": "h", "patches": []}]}}
    # Second page returns empty devices — loop should break
    page2 = {"prepatch": {"total": 100, "devices": []}}

    client = StubClient(
        get_responses={"/reports/prepatch": [page1, page2]},
    )

    result = await get_prepatch_report(cast(AutomoxClient, client), org_id=42)

    get_calls = [c for c in client.calls if c[0] == "GET"]
    assert len(get_calls) == 2
    assert result["data"]["total_devices"] == 1


# ===========================================================================
# get_noncompliant_report
# ===========================================================================


def _make_noncompliant_response(
    devices: list[dict[str, Any]],
    total: int = 0,
) -> dict[str, Any]:
    return {
        "nonCompliant": {
            "total": total or len(devices),
            "devices": devices,
        }
    }


@pytest.mark.asyncio
async def test_get_noncompliant_report_basic() -> None:
    device = {
        "id": 10,
        "name": "noncompliant-host",
        "groupId": 5,
        "os_family": "Linux",
        "connected": True,
        "needsReboot": False,
        "lastRefreshTime": "2024-01-01T00:00:00Z",
    }
    client = StubClient(
        get_responses={"/reports/needs-attention": [_make_noncompliant_response([device])]},
    )

    result = await get_noncompliant_report(
        cast(AutomoxClient, client),
        org_id=42,
    )

    data = result["data"]
    assert data["total_devices"] == 1
    dev = data["devices"][0]
    assert dev["server_id"] == 10
    assert dev["server_name"] == "noncompliant-host"
    assert dev["server_group_id"] == 5
    assert dev["os_family"] == "Linux"
    assert dev["last_refresh_time"] == "2024-01-01T00:00:00Z"
    assert "failing_policies" not in dev


@pytest.mark.asyncio
async def test_get_noncompliant_report_with_failing_policies() -> None:
    device = {
        "id": 20,
        "name": "device-with-failures",
        "policies": [
            {"id": 101, "name": "Policy A"},
            {"id": 102, "name": "Policy B"},
        ],
    }
    client = StubClient(
        get_responses={"/reports/needs-attention": [_make_noncompliant_response([device])]},
    )

    result = await get_noncompliant_report(
        cast(AutomoxClient, client),
        org_id=42,
    )

    dev = result["data"]["devices"][0]
    assert "failing_policies" in dev
    assert len(dev["failing_policies"]) == 2
    policy_ids = [p["id"] for p in dev["failing_policies"]]
    assert 101 in policy_ids
    assert 102 in policy_ids


@pytest.mark.asyncio
async def test_get_noncompliant_report_with_group_id_and_pagination() -> None:
    """group_id, limit, and offset are forwarded to the API."""
    client = StubClient(
        get_responses={"/reports/needs-attention": [_make_noncompliant_response([])]},
    )

    await get_noncompliant_report(
        cast(AutomoxClient, client),
        org_id=42,
        group_id=3,
        limit=50,
        offset=25,
    )

    params = client.calls[0][2]
    assert params is not None
    assert params["groupId"] == 3
    assert params["limit"] == 50
    assert params["offset"] == 25


@pytest.mark.asyncio
async def test_get_noncompliant_report_custom_name_fallback() -> None:
    """server_name falls back to customName when name is absent."""
    device = {"id": 30, "customName": "My Custom Device"}
    client = StubClient(
        get_responses={"/reports/needs-attention": [_make_noncompliant_response([device])]},
    )

    result = await get_noncompliant_report(
        cast(AutomoxClient, client),
        org_id=42,
    )

    dev = result["data"]["devices"][0]
    assert dev["server_name"] == "My Custom Device"


@pytest.mark.asyncio
async def test_get_noncompliant_report_empty() -> None:
    client = StubClient(
        get_responses={"/reports/needs-attention": [_make_noncompliant_response([])]},
    )

    result = await get_noncompliant_report(
        cast(AutomoxClient, client),
        org_id=42,
    )

    assert result["data"]["total_devices"] == 0
    assert result["data"]["devices"] == []


@pytest.mark.asyncio
async def test_get_noncompliant_report_non_mapping_items_skipped() -> None:
    """Non-Mapping items in the device list are silently skipped."""
    response = {
        "nonCompliant": {
            "total": 2,
            "devices": ["not-a-dict", {"id": 50, "name": "real-device"}],
        }
    }
    client = StubClient(
        get_responses={"/reports/needs-attention": [response]},
    )

    result = await get_noncompliant_report(
        cast(AutomoxClient, client),
        org_id=42,
    )

    assert len(result["data"]["devices"]) == 1
    assert result["data"]["devices"][0]["server_id"] == 50


@pytest.mark.asyncio
async def test_get_noncompliant_report_uses_len_when_total_absent() -> None:
    """When API summary has no 'total', total_devices falls back to len(devices)."""
    response = {
        "nonCompliant": {
            # no "total" key
            "devices": [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}],
        }
    }
    client = StubClient(
        get_responses={"/reports/needs-attention": [response]},
    )

    result = await get_noncompliant_report(
        cast(AutomoxClient, client),
        org_id=42,
    )

    assert result["data"]["total_devices"] == 2


# ===========================================================================
# Error path tests — API errors propagate through the workflow
# ===========================================================================


@pytest.mark.asyncio
async def test_prepatch_report_api_error_propagates():
    client = StubClient()

    async def _raise(*a: Any, **kw: Any) -> Any:
        raise AutomoxAPIError("timeout", status_code=504)

    client.get = _raise  # type: ignore[assignment]
    with pytest.raises(AutomoxAPIError, match="timeout"):
        await get_prepatch_report(cast(AutomoxClient, client), org_id=1)
