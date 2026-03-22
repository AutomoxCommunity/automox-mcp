"""Tests for compound workflows (get_patch_tuesday_readiness, get_compliance_snapshot,
get_device_full_profile)."""

import copy
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from automox_mcp.client import AutomoxAPIError, AutomoxClient
from automox_mcp.workflows.compound import (
    get_compliance_snapshot,
    get_device_full_profile,
    get_patch_tuesday_readiness,
)
from conftest import StubClient


# ---------------------------------------------------------------------------
# Prepatch report / approval / policy fixtures
# ---------------------------------------------------------------------------

_PREPATCH_RESPONSE = {
    "prepatch": {
        "total": 2,
        "devices": [
            {
                "id": 101,
                "name": "web-01",
                "group": "Production",
                "os_family": "Windows",
                "connected": True,
                "compliant": False,
                "needsReboot": False,
                "patches": [{"name": "KB001", "severity": "critical"}],
            },
            {
                "id": 102,
                "name": "web-02",
                "group": "Staging",
                "os_family": "Linux",
                "connected": True,
                "compliant": True,
                "needsReboot": True,
                "patches": [{"name": "openssl-1.1"}, {"name": "curl-8.0"}],
            },
        ],
    }
}

_APPROVALS_RESPONSE = [
    {
        "id": 201,
        "title": "Chrome 120",
        "status": "pending",
        "severity": "high",
        "device_count": 5,
    },
    {
        "id": 202,
        "title": "Firefox 121",
        "status": "approved",
        "severity": "medium",
        "device_count": 3,
    },
]

_POLICIES_RESPONSE = [
    {
        "id": 301,
        "guid": "11111111-1111-1111-1111-111111111111",
        "name": "Weekday Patching",
        "policy_type": "patch",
        "active": True,
        "status": "active",
        "schedule_days": 62,
        "schedule_time": "02:00",
    },
    {
        "id": 302,
        "guid": "22222222-2222-2222-2222-222222222222",
        "name": "Custom Compliance",
        "policy_type": "custom",
        "active": True,
        "status": "active",
    },
]

_POLICYSTATS_RESPONSE = [
    {"policy_id": 301, "policy_name": "Weekday Patching", "compliant": 8, "non_compliant": 2},
    {"policy_id": 302, "policy_name": "Custom Compliance", "compliant": 10, "non_compliant": 0},
]

_NONCOMPLIANT_RESPONSE = {
    "nonCompliant": {
        "total": 3,
        "devices": [
            {
                "id": 101,
                "name": "web-01",
                "groupId": 10,
                "os_family": "Windows",
                "connected": True,
                "needsReboot": False,
                "policies": [{"id": 301, "name": "Weekday Patching"}],
            },
        ],
    }
}


def _build_readiness_client() -> StubClient:
    client = StubClient(
        get_responses={
            "/reports/prepatch": [_PREPATCH_RESPONSE],
            "/approvals": [_APPROVALS_RESPONSE],
            "/policies": [_POLICIES_RESPONSE],
            "/policystats": [_POLICYSTATS_RESPONSE],
        }
    )
    client.org_id = 555
    return client


def _build_compliance_client() -> StubClient:
    client = StubClient(
        get_responses={
            "/reports/needs-attention": [_NONCOMPLIANT_RESPONSE],
            "/servers": [
                [
                    {
                        "id": 101,
                        "managed": True,
                        "status": {"policy_status": "failed"},
                        "last_check_in": "2025-03-01T12:00:00Z",
                    },
                    {
                        "id": 102,
                        "managed": True,
                        "status": {"policy_status": "success"},
                        "last_check_in": "2025-03-18T12:00:00Z",
                    },
                    {
                        "id": 103,
                        "managed": True,
                        "status": {"policy_status": "success"},
                        "last_check_in": "2025-03-18T12:00:00Z",
                    },
                ]
            ],
            "/policies": [_POLICIES_RESPONSE],
            "/policystats": [_POLICYSTATS_RESPONSE],
        }
    )
    client.org_id = 555
    return client


# ---------------------------------------------------------------------------
# Tests: get_patch_tuesday_readiness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_tuesday_readiness_returns_all_sections() -> None:
    client = _build_readiness_client()
    result = await get_patch_tuesday_readiness(
        cast(AutomoxClient, client),
        org_id=555,
        org_uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    )

    data = result["data"]
    # Prepatch section populated
    assert data["prepatch_report"]["total_devices_needing_patches"] > 0
    assert len(data["prepatch_report"]["devices"]) == 2

    # Approvals section populated
    assert data["patch_approvals"]["pending_count"] == 1  # only one "pending"

    # Policy schedules section populated
    patch_schedules = data["patch_policy_schedules"]
    assert len(patch_schedules) == 1  # only the patch policy, not the custom one
    assert patch_schedules[0]["name"] == "Weekday Patching"

    # Readiness summary
    summary = data["readiness_summary"]
    assert summary["pending_approvals"] == 1
    assert summary["active_patch_policies"] >= 1


@pytest.mark.asyncio
async def test_patch_tuesday_readiness_with_group_filter() -> None:
    client = _build_readiness_client()
    await get_patch_tuesday_readiness(
        cast(AutomoxClient, client),
        org_id=555,
        org_uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        group_id=10,
    )

    # Verify that group_id was passed to the prepatch report call
    prepatch_calls = [c for c in client.calls if c[1] == "/reports/prepatch"]
    assert len(prepatch_calls) >= 1
    assert prepatch_calls[0][2]["groupId"] == 10


@pytest.mark.asyncio
async def test_patch_tuesday_readiness_handles_partial_failures() -> None:
    """If one sub-report fails, the others should still populate."""
    from automox_mcp.client import AutomoxAPIError

    class FailingPrepatchClient(StubClient):
        async def get(self, path, *, params=None, headers=None):
            if path == "/reports/prepatch":
                raise AutomoxAPIError("Forbidden", status_code=403)
            return await super().get(path, params=params, headers=headers)

    client = FailingPrepatchClient(
        get_responses={
            "/approvals": [_APPROVALS_RESPONSE],
            "/policies": [_POLICIES_RESPONSE],
            "/policystats": [_POLICYSTATS_RESPONSE],
        }
    )
    client.org_id = 555

    result = await get_patch_tuesday_readiness(
        cast(AutomoxClient, client),
        org_id=555,
        org_uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    )

    # Approvals should still work despite prepatch failure
    assert result["data"]["patch_approvals"]["pending_count"] == 1
    # Errors should be recorded
    errors = result["metadata"].get("errors")
    assert errors is not None
    assert any("prepatch" in e for e in errors)


@pytest.mark.asyncio
async def test_patch_tuesday_readiness_no_errors_when_all_succeed() -> None:
    client = _build_readiness_client()
    result = await get_patch_tuesday_readiness(
        cast(AutomoxClient, client),
        org_id=555,
        org_uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    )

    assert result["metadata"].get("errors") is None


# ---------------------------------------------------------------------------
# Tests: get_compliance_snapshot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compliance_snapshot_returns_all_sections() -> None:
    client = _build_compliance_client()
    result = await get_compliance_snapshot(
        cast(AutomoxClient, client),
        org_id=555,
    )

    data = result["data"]

    # Compliance overview
    overview = data["compliance_overview"]
    assert overview["total_devices"] > 0
    assert overview["noncompliant_devices"] > 0
    assert 0 <= overview["compliance_rate_percent"] <= 100

    # Noncompliant report
    assert len(data["noncompliant_report"]["devices"]) >= 1

    # Policy summary
    assert data["policy_summary"]["total_policies"] > 0
    assert "patch" in data["policy_summary"]["by_type"]


@pytest.mark.asyncio
async def test_compliance_snapshot_computes_rate_correctly() -> None:
    client = _build_compliance_client()
    result = await get_compliance_snapshot(
        cast(AutomoxClient, client),
        org_id=555,
    )

    overview = result["data"]["compliance_overview"]
    total = overview["total_devices"]
    noncompliant = overview["noncompliant_devices"]
    compliant = overview["compliant_devices"]
    rate = overview["compliance_rate_percent"]

    assert compliant + noncompliant <= total
    if total > 0:
        expected_rate = round(compliant / total * 100, 1)
        assert rate == expected_rate


@pytest.mark.asyncio
async def test_compliance_snapshot_handles_empty_org() -> None:
    """An org with no devices should return 0% compliance, not a division error."""
    client = StubClient(
        get_responses={
            "/reports/needs-attention": [{"nonCompliant": {"total": 0, "devices": []}}],
            "/servers": [[]],
            "/policies": [[]],
            "/policystats": [[]],
        }
    )
    client.org_id = 555

    result = await get_compliance_snapshot(
        cast(AutomoxClient, client),
        org_id=555,
    )

    overview = result["data"]["compliance_overview"]
    assert overview["total_devices"] == 0
    assert overview["compliance_rate_percent"] == 0


@pytest.mark.asyncio
async def test_compliance_snapshot_records_errors_on_partial_failure() -> None:
    """If the noncompliant report fails, the rest should still work."""
    from automox_mcp.client import AutomoxAPIError

    class FailingNoncompliantClient(StubClient):
        async def get(self, path, *, params=None, headers=None):
            if path == "/reports/needs-attention":
                raise AutomoxAPIError("Forbidden", status_code=403)
            return await super().get(path, params=params, headers=headers)

    client = FailingNoncompliantClient(
        get_responses={
            "/servers": [
                [
                    {
                        "id": 1,
                        "managed": True,
                        "status": {"policy_status": "success"},
                        "last_check_in": "2025-03-18T12:00:00Z",
                    }
                ]
            ],
            "/policies": [_POLICIES_RESPONSE],
            "/policystats": [_POLICYSTATS_RESPONSE],
        }
    )
    client.org_id = 555

    result = await get_compliance_snapshot(
        cast(AutomoxClient, client),
        org_id=555,
    )

    errors = result["metadata"].get("errors")
    assert errors is not None
    assert any("noncompliant" in e for e in errors)
    # Policy summary should still be populated
    assert result["data"]["policy_summary"]["total_policies"] > 0


# ---------------------------------------------------------------------------
# Fixtures: get_device_full_profile
# ---------------------------------------------------------------------------

_DEVICE_DETAIL_RESPONSE: dict[str, Any] = {
    "data": {
        "core": {
            "id": 101,
            "name": "web-01",
            "os_family": "Windows",
            "ip_addrs": ["10.0.0.1"],
            "connected": True,
        },
        "policy_assignments": {
            "total": 2,
            "policies": [
                {"id": 301, "name": "Weekday Patching"},
                {"id": 302, "name": "Custom Compliance"},
            ],
        },
        "pending_commands": [{"command": "scan", "status": "queued"}],
        "device_facts": {"os_version": "10.0.19045"},
    },
    "metadata": {},
}

_INVENTORY_RESPONSE: dict[str, Any] = {
    "data": {
        "device_id": 101,
        "device_uuid": "dddddddd-dddd-dddd-dddd-dddddddddddd",
        "total_categories": 2,
        "total_items": 5,
        "categories": {
            "Hardware": {
                "name": "Hardware",
                "sub_categories": {
                    "Processor": {
                        "item_count": 2,
                        "items": [
                            {
                                "name": "cpu_name",
                                "friendly_name": "CPU Name",
                                "value": "Intel i7",
                                "type": "string",
                                "collected_at": "2026-03-20T00:00:00Z",
                            },
                            {
                                "name": "cpu_cores",
                                "friendly_name": "CPU Cores",
                                "value": 8,
                                "type": "integer",
                                "collected_at": "2026-03-20T00:00:00Z",
                            },
                        ],
                    },
                },
            },
            "Network": {
                "name": "Network",
                "sub_categories": {
                    "Interfaces": {
                        "item_count": 3,
                        "items": [
                            {
                                "name": "mac_address",
                                "friendly_name": "MAC Address",
                                "value": "AA:BB:CC:DD:EE:FF",
                                "type": "string",
                                "collected_at": "2026-03-20T00:00:00Z",
                            },
                            {
                                "name": "ip_address",
                                "friendly_name": "IP Address",
                                "value": "10.0.0.1",
                                "type": "string",
                                "collected_at": "2026-03-20T00:00:00Z",
                            },
                            {
                                "name": "connected",
                                "friendly_name": "Connected",
                                "value": True,
                                "type": "boolean",
                                "collected_at": "2026-03-20T00:00:00Z",
                            },
                        ],
                    },
                },
            },
        },
    },
    "metadata": {},
}

_PACKAGES_RESPONSE: dict[str, Any] = {
    "data": {
        "device_id": 101,
        "total_packages": 3,
        "packages": [
            {"id": 1, "name": "Chrome", "version": "120.0", "severity": "high"},
            {"id": 2, "name": "Firefox", "version": "121.0", "severity": "medium"},
            {"id": 3, "name": "curl", "version": "8.0", "severity": "low"},
        ],
    },
    "metadata": {},
}


def _patch_sub_workflows(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> None:
    """Monkeypatch the three sub-workflow functions called by get_device_full_profile.

    Accesses the function's __globals__ to find the exact module objects it references,
    which is necessary because test_tools.py invalidates sys.modules cache mid-suite.
    """
    fn_globals = get_device_full_profile.__globals__
    devices_mod = fn_globals["devices"]
    packages_mod = fn_globals["packages"]

    monkeypatch.setattr(
        devices_mod,
        "describe_device",
        overrides.get(
            "describe_device", AsyncMock(return_value=copy.deepcopy(_DEVICE_DETAIL_RESPONSE))
        ),
    )
    monkeypatch.setattr(
        devices_mod,
        "get_device_inventory",
        overrides.get(
            "get_device_inventory", AsyncMock(return_value=copy.deepcopy(_INVENTORY_RESPONSE))
        ),
    )
    monkeypatch.setattr(
        packages_mod,
        "list_device_packages",
        overrides.get(
            "list_device_packages", AsyncMock(return_value=copy.deepcopy(_PACKAGES_RESPONSE))
        ),
    )


# ---------------------------------------------------------------------------
# Tests: get_device_full_profile
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_profile_returns_all_sections(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_sub_workflows(monkeypatch)
    client = StubClient()

    result = await get_device_full_profile(
        cast(AutomoxClient, client), org_id=555, device_id=101,
    )

    data = result["data"]
    assert data["device"]["name"] == "web-01"
    assert data["policy_assignments"]["total"] == 2
    assert len(data["pending_commands"]) == 1
    assert data["inventory"]["total_categories"] == 2
    assert data["inventory"]["total_items"] == 5
    assert data["packages"]["total"] == 3
    assert result["metadata"]["data_complete"] is True
    assert result["metadata"]["errors"] is None


@pytest.mark.asyncio
async def test_full_profile_inventory_summarizes_key_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inventory should be summarized with scalar key-values per sub-category."""
    _patch_sub_workflows(monkeypatch)
    client = StubClient()

    result = await get_device_full_profile(
        cast(AutomoxClient, client), org_id=555, device_id=101,
    )

    hw = result["data"]["inventory"]["categories"]["Hardware"]
    assert hw["sub_category_count"] == 1
    proc = hw["sub_categories"]["Processor"]
    assert proc["item_count"] == 2
    assert proc["key_values"]["CPU Name"] == "Intel i7"
    assert proc["key_values"]["CPU Cores"] == 8
    assert None not in proc["key_values"]  # no None keys from unnamed items


@pytest.mark.asyncio
async def test_full_profile_skips_unnamed_inventory_items(monkeypatch: pytest.MonkeyPatch) -> None:
    """Items without friendly_name or name should be excluded from key_values."""
    inv_with_unnamed = copy.deepcopy(_INVENTORY_RESPONSE)
    # Add an item with no name fields
    inv_with_unnamed["data"]["categories"]["Hardware"]["sub_categories"]["Processor"]["items"].append(
        {
            "name": None,
            "friendly_name": None,
            "value": "mystery",
            "type": "string",
            "collected_at": None,
        },
    )
    _patch_sub_workflows(
        monkeypatch,
        get_device_inventory=AsyncMock(return_value=inv_with_unnamed),
    )
    client = StubClient()

    result = await get_device_full_profile(
        cast(AutomoxClient, client), org_id=555, device_id=101,
    )

    proc = result["data"]["inventory"]["categories"]["Hardware"]["sub_categories"]["Processor"]
    assert None not in proc["key_values"]
    assert "mystery" not in proc["key_values"].values()


@pytest.mark.asyncio
async def test_full_profile_truncates_packages(monkeypatch: pytest.MonkeyPatch) -> None:
    """When total packages exceed max_packages, the list should be truncated."""
    many_packages = {
        "data": {
            "device_id": 101,
            "total_packages": 50,
            "packages": [{"id": i, "name": f"pkg-{i}", "version": "1.0"} for i in range(50)],
        },
        "metadata": {},
    }
    _patch_sub_workflows(
        monkeypatch,
        list_device_packages=AsyncMock(return_value=many_packages),
    )
    client = StubClient()

    result = await get_device_full_profile(
        cast(AutomoxClient, client), org_id=555, device_id=101, max_packages=5,
    )

    pkg_section = result["data"]["packages"]
    assert pkg_section["total"] == 50
    assert pkg_section["returned"] == 5
    assert pkg_section["truncated"] is True
    assert "use list_device_packages" in pkg_section["note"]


@pytest.mark.asyncio
async def test_full_profile_no_truncation_when_within_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_sub_workflows(monkeypatch)
    client = StubClient()

    result = await get_device_full_profile(
        cast(AutomoxClient, client), org_id=555, device_id=101,
    )

    pkg_section = result["data"]["packages"]
    assert pkg_section["truncated"] is False
    assert pkg_section["note"] is None


@pytest.mark.asyncio
async def test_full_profile_handles_partial_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """If inventory fails, device detail and packages should still populate."""
    _patch_sub_workflows(
        monkeypatch,
        get_device_inventory=AsyncMock(side_effect=AutomoxAPIError("Not Found", status_code=404)),
    )
    client = StubClient()

    result = await get_device_full_profile(
        cast(AutomoxClient, client), org_id=555, device_id=101,
    )

    assert result["metadata"]["data_complete"] is False
    assert result["metadata"]["section_status"]["device_inventory"] == "failed"
    assert result["metadata"]["section_status"]["device_detail"] == "complete"
    assert result["metadata"]["section_status"]["device_packages"] == "complete"
    assert any("device_inventory" in e for e in result["metadata"]["errors"])
    # Other sections still populated
    assert result["data"]["device"]["name"] == "web-01"
    assert result["data"]["packages"]["total"] == 3


@pytest.mark.asyncio
async def test_full_profile_all_sections_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """If all sub-workflows fail, result should be empty but structured."""
    _patch_sub_workflows(
        monkeypatch,
        describe_device=AsyncMock(side_effect=AutomoxAPIError("Forbidden", status_code=403)),
        get_device_inventory=AsyncMock(side_effect=AutomoxAPIError("Forbidden", status_code=403)),
        list_device_packages=AsyncMock(side_effect=AutomoxAPIError("Forbidden", status_code=403)),
    )
    client = StubClient()

    result = await get_device_full_profile(
        cast(AutomoxClient, client), org_id=555, device_id=101,
    )

    assert result["metadata"]["data_complete"] is False
    assert len(result["metadata"]["errors"]) == 3
    for section in ("device_detail", "device_inventory", "device_packages"):
        assert result["metadata"]["section_status"][section] == "failed"
    # Data sections should be empty but present
    assert result["data"]["device"] == {}
    assert result["data"]["inventory"]["total_categories"] == 0
    assert result["data"]["packages"]["total"] == 0


@pytest.mark.asyncio
async def test_full_profile_metadata_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_sub_workflows(monkeypatch)
    client = StubClient()

    result = await get_device_full_profile(
        cast(AutomoxClient, client), org_id=555, device_id=101,
    )

    counts = result["metadata"]["counts"]
    assert counts["inventory_categories"] == 2
    assert counts["inventory_items"] == 5
    assert counts["packages_total"] == 3
    assert counts["packages_returned"] == 3
    assert counts["policy_assignments"] == 2
    assert counts["pending_commands"] == 1
