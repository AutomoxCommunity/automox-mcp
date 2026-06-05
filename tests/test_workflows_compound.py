"""Tests for compound workflows (get_patch_tuesday_readiness, get_compliance_snapshot,
get_device_full_profile)."""

import copy
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxAPIError, AutomoxClient
from automox_mcp.workflows.compound import (
    get_compliance_snapshot,
    get_device_full_profile,
    get_patch_tuesday_readiness,
)

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

# Spec-shaped /approvals envelope (components/schemas/Approvals): a
# {size, results} wrapper whose items carry software/policy blocks and
# manual_approval — NOT the flat title/severity/device_count shape the old
# fixture invented (which let the silent-zero envelope bug pass tests).
_APPROVALS_RESPONSE = {
    "size": 2,
    "results": [
        {
            "id": 201,
            "manual_approval": None,
            "manual_approval_time": None,
            "status": "pending",
            "software": {
                "id": 137,
                "software_version_id": 324,
                "display_name": "Chrome 120",
                "version": "120.0.1",
                "os_family": "Windows",
                "cves": ["CVE-2026-0001", "CVE-2026-0002"],
            },
            "policy": {"id": 301, "name": "Weekday Patching"},
        },
        {
            "id": 202,
            "manual_approval": True,
            "manual_approval_time": "2026-06-01T12:00:00Z",
            "status": "approved",
            "software": {
                "id": 138,
                "software_version_id": 325,
                "display_name": "Firefox 121",
                "version": "121.0",
                "os_family": "Mac",
                "cves": [],
            },
            "policy": {"id": 301, "name": "Weekday Patching"},
        },
    ],
}

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
    # schedule_days bitmask 62 is decoded so the model never reads it raw
    assert patch_schedules[0]["schedule_days_decoded"] == "Weekdays (Monday through Friday)"

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
async def test_patch_tuesday_readiness_caps_inner_lists_at_detail_limit() -> None:
    """#53 contract: each inner list is capped at detail_limit; truncated
    sections surface metadata.section_summaries with follow-up tool hints."""
    # 30 prepatch devices, 30 approvals, 30 patch policies — well over the
    # default detail_limit=10.
    devices_payload = {
        "prepatch": {
            "devices": [
                {"id": i, "name": f"host-{i}", "patches": [{"severity": "high"}] * 3}
                for i in range(30)
            ],
            "total": 30,
        }
    }
    approvals_payload = {
        "size": 30,
        "results": [
            {
                "id": i,
                "status": "pending",
                "manual_approval": None,
                "software": {"display_name": f"Approval {i}", "version": "1.0", "cves": []},
                "policy": {"id": 1, "name": "P"},
            }
            for i in range(30)
        ],
    }
    policies_payload = [
        {
            "id": 1000 + i,
            "name": f"Patch Policy {i}",
            "policy_type_name": "patch",
            "status": "active",
            "schedule_days": 124,
            "schedule_time": "02:00",
        }
        for i in range(30)
    ]
    client = StubClient(
        get_responses={
            "/reports/prepatch": [devices_payload],
            "/approvals": [approvals_payload],
            "/policies": [policies_payload],
            "/policystats": [[]],
        }
    )
    client.org_id = 555

    result = await get_patch_tuesday_readiness(
        cast(AutomoxClient, client),
        org_id=555,
        org_uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        detail_limit=10,
    )

    data = result["data"]
    # Each preview is capped.
    assert len(data["prepatch_report"]["devices"]) == 10
    assert len(data["patch_approvals"]["approvals"]) == 10
    assert len(data["patch_policy_schedules"]) == 10

    # Counts remain accurate.
    assert data["prepatch_report"]["total_devices_needing_patches"] == 30
    assert data["readiness_summary"]["devices_needing_patches"] == 30

    # Section summaries surface the truncation + follow-up tool.
    summaries = result["metadata"]["section_summaries"]
    assert summaries["prepatch_report.devices"] == {
        "total": 30,
        "returned": 10,
        "has_more": True,
        # Registered tool name is `prepatch_report` (no `get_` prefix); the
        # earlier `get_prepatch_report` value was a real bug — LLMs following
        # the hint hit `Unknown tool` errors. See v1.0.30 / sweep finding.
        "follow_up_tool": "prepatch_report",
        "follow_up_args_hint": {},
    }
    assert summaries["patch_approvals.approvals"]["follow_up_tool"] == "patch_approvals_summary"
    assert summaries["patch_policy_schedules"]["follow_up_tool"] == "policy_catalog"

    # Notes are LLM-friendly hints; one per truncated section.
    notes = result["metadata"]["notes"]
    assert len(notes) == 3
    assert all("call `" in n for n in notes)


@pytest.mark.asyncio
async def test_patch_tuesday_readiness_detail_limit_zero_returns_summary_only() -> None:
    """detail_limit=0 — pure summary mode. Inner lists are empty but counts and
    section_summaries describe what was omitted."""
    devices_payload = {
        "prepatch": {
            "devices": [{"id": i, "name": f"host-{i}"} for i in range(5)],
            "total": 5,
        }
    }
    approvals_payload = {
        "size": 5,
        "results": [{"id": i, "title": f"A{i}", "status": "pending"} for i in range(5)],
    }
    policies_payload = [
        {"id": 1000 + i, "name": f"P{i}", "policy_type_name": "patch", "status": "active"}
        for i in range(3)
    ]
    client = StubClient(
        get_responses={
            "/reports/prepatch": [devices_payload],
            "/approvals": [approvals_payload],
            "/policies": [policies_payload],
            "/policystats": [[]],
        }
    )
    client.org_id = 555

    result = await get_patch_tuesday_readiness(
        cast(AutomoxClient, client),
        org_id=555,
        org_uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        detail_limit=0,
    )

    assert result["data"]["prepatch_report"]["devices"] == []
    assert result["data"]["patch_approvals"]["approvals"] == []
    assert result["data"]["patch_policy_schedules"] == []
    # Counts intact.
    assert result["data"]["prepatch_report"]["total_devices_needing_patches"] == 5
    assert result["data"]["patch_approvals"]["pending_count"] == 5
    # All three sections summarized.
    assert set(result["metadata"]["section_summaries"]) == {
        "prepatch_report.devices",
        "patch_approvals.approvals",
        "patch_policy_schedules",
    }


@pytest.mark.asyncio
async def test_patch_tuesday_readiness_no_summary_when_under_limit() -> None:
    """If a section is already under detail_limit, no truncation metadata for it."""
    devices_payload = {"prepatch": {"devices": [], "total": 0}}
    approvals_payload: list[Any] = []
    policies_payload = [
        {"id": 1, "name": "P1", "policy_type_name": "patch", "status": "active"},
        {"id": 2, "name": "P2", "policy_type_name": "patch", "status": "active"},
    ]
    client = StubClient(
        get_responses={
            "/reports/prepatch": [devices_payload],
            "/approvals": [approvals_payload],
            "/policies": [policies_payload],
            "/policystats": [[]],
        }
    )
    client.org_id = 555

    result = await get_patch_tuesday_readiness(
        cast(AutomoxClient, client),
        org_id=555,
        org_uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        detail_limit=10,
    )

    # No truncation metadata when everything fits.
    assert result["metadata"].get("section_summaries") is None
    assert "notes" not in result["metadata"]


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
        cast(AutomoxClient, client),
        org_id=555,
        device_id=101,
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
        cast(AutomoxClient, client),
        org_id=555,
        device_id=101,
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
    inv_with_unnamed["data"]["categories"]["Hardware"]["sub_categories"]["Processor"][
        "items"
    ].append(
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
        cast(AutomoxClient, client),
        org_id=555,
        device_id=101,
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
        cast(AutomoxClient, client),
        org_id=555,
        device_id=101,
        max_packages=5,
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
        cast(AutomoxClient, client),
        org_id=555,
        device_id=101,
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
        cast(AutomoxClient, client),
        org_id=555,
        device_id=101,
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
        cast(AutomoxClient, client),
        org_id=555,
        device_id=101,
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
        cast(AutomoxClient, client),
        org_id=555,
        device_id=101,
    )

    counts = result["metadata"]["counts"]
    assert counts["inventory_categories"] == 2
    assert counts["inventory_items"] == 5
    assert counts["packages_total"] == 3
    assert counts["packages_returned"] == 3
    assert counts["policy_assignments"] == 2
    assert counts["pending_commands"] == 1


# ---------------------------------------------------------------------------
# #53 sweep: detail_limit contract on get_compliance_snapshot and
# get_device_full_profile.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compliance_snapshot_caps_inner_lists_at_detail_limit() -> None:
    """#53: noncompliant_report.devices and device_health.stale_devices are
    capped at detail_limit; metadata.section_summaries points at the detail
    tools for full data."""
    noncompliant_payload = {
        "nonCompliant": {
            "total": 30,
            "devices": [{"id": i, "name": f"host-{i}", "groupId": 10} for i in range(30)],
        }
    }
    # 30 servers all marked stale (no recent check-in)
    servers_payload = [
        {
            "id": 1000 + i,
            "managed": True,
            "status": {"policy_status": "success"},
            "last_check_in": "2024-01-01T00:00:00Z",
        }
        for i in range(30)
    ]
    client = StubClient(
        get_responses={
            "/reports/needs-attention": [noncompliant_payload],
            "/servers": [servers_payload],
            "/policies": [_POLICIES_RESPONSE],
            "/policystats": [_POLICYSTATS_RESPONSE],
        }
    )
    client.org_id = 555

    result = await get_compliance_snapshot(
        cast(AutomoxClient, client),
        org_id=555,
        detail_limit=10,
    )

    data = result["data"]
    assert len(data["noncompliant_report"]["devices"]) == 10
    assert len(data["device_health"]["stale_devices"]) <= 10
    # Counts unaffected.
    assert data["compliance_overview"]["noncompliant_devices"] == 30

    summaries = result["metadata"]["section_summaries"]
    assert summaries["noncompliant_report.devices"]["total"] == 30
    assert summaries["noncompliant_report.devices"]["returned"] == 10
    # Registered tool name is `noncompliant_report` (no `get_` prefix); the
    # earlier `get_noncompliant_report` value was a real bug — LLMs following
    # the hint hit `Unknown tool` errors. See v1.0.30 / sweep finding.
    assert summaries["noncompliant_report.devices"]["follow_up_tool"] == "noncompliant_report"
    assert summaries["device_health.stale_devices"]["follow_up_tool"] == "device_health_metrics"
    # LLM-friendly notes.
    notes = result["metadata"]["notes"]
    assert any("noncompliant_report" in n for n in notes)


@pytest.mark.asyncio
async def test_compliance_snapshot_no_summary_when_under_limit() -> None:
    """Already-small sections shouldn't surface section_summaries."""
    client = _build_compliance_client()
    result = await get_compliance_snapshot(
        cast(AutomoxClient, client),
        org_id=555,
        detail_limit=10,
    )
    assert result["metadata"].get("section_summaries") is None


@pytest.mark.asyncio
async def test_full_profile_emits_section_summary_for_truncated_packages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#53: packages.packages truncation surfaces via metadata.section_summaries
    in addition to the legacy packages.truncated / packages.note fields."""
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
        cast(AutomoxClient, client),
        org_id=555,
        device_id=101,
        detail_limit=5,
    )

    # Canonical section summary present.
    summaries = result["metadata"]["section_summaries"]
    assert summaries["packages.packages"] == {
        "total": 50,
        "returned": 5,
        "has_more": True,
        "follow_up_tool": "list_device_packages",
        "follow_up_args_hint": {"device_id": 101},
    }
    # Legacy fields still emitted for backwards-compat.
    pkg_section = result["data"]["packages"]
    assert pkg_section["truncated"] is True
    assert "use list_device_packages" in pkg_section["note"]
    # detail_limit recorded in metadata.
    assert result["metadata"]["detail_limit"] == 5


@pytest.mark.asyncio
async def test_full_profile_detail_limit_falls_back_to_max_packages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy callers passing only max_packages still get the old behavior."""
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

    # Only max_packages set, no detail_limit
    result = await get_device_full_profile(
        cast(AutomoxClient, client),
        org_id=555,
        device_id=101,
        max_packages=7,
    )

    assert result["data"]["packages"]["returned"] == 7
    assert result["metadata"]["detail_limit"] == 7


# ===========================================================================
# Contract enforcement: every `follow_up_tool` in compound responses must
# resolve to an actually-registered tool name.
#
# This was a real bug: get_patch_tuesday_readiness and get_compliance_snapshot
# both emitted follow_up_tool="get_prepatch_report" / "get_noncompliant_report"
# while the registered tool names are `prepatch_report` and `noncompliant_report`
# (no `get_` prefix). LLMs following the contract's hint got `Unknown tool`
# errors. Surfaced by tests/exploratory_sweep.py.
# ===========================================================================


def _collect_follow_up_tools(metadata: dict[str, Any]) -> set[str]:
    """Extract every follow_up_tool value from a compound-tool metadata block."""
    out: set[str] = set()
    sections = metadata.get("section_summaries") or {}
    if isinstance(sections, dict):
        for info in sections.values():
            if isinstance(info, dict):
                tool = info.get("follow_up_tool")
                if isinstance(tool, str):
                    out.add(tool)
    return out


def _all_registered_tool_names() -> set[str]:
    """Register every tool module against a fresh FastMCP and return tool names.

    Bypasses environment-driven module filtering so the assertion covers the
    complete tool surface — any compound tool whose follow_up dispatch points
    at a name outside this set is broken.
    """
    import importlib

    from fastmcp import FastMCP

    from automox_mcp.tools import _MODULE_REGISTRY, _get_tool_names

    server = FastMCP("contract-check")
    client = StubClient()
    for _, (tool_module, _has_writes) in _MODULE_REGISTRY.items():
        mod = importlib.import_module(f"automox_mcp.tools.{tool_module}")
        # Register with writes enabled so destructive tools are also captured.
        mod.register(server, read_only=False, client=cast(AutomoxClient, client))
    return _get_tool_names(server)


@pytest.mark.asyncio
async def test_patch_tuesday_follow_up_tools_are_registered() -> None:
    """Every `follow_up_tool` emitted by get_patch_tuesday_readiness must be
    the name of an actually-registered tool. Regression: v1.0.27 shipped with
    `get_prepatch_report` here, which does not resolve."""
    # Force truncation so all three section_summaries fire.
    devices = [{"id": i, "name": f"h-{i}", "patches": [{"severity": "high"}]} for i in range(30)]
    approvals = [{"id": i, "status": "pending", "severity": "high"} for i in range(30)]
    policies = [
        {
            "id": 1000 + i,
            "name": f"P{i}",
            "policy_type_name": "patch",
            "status": "active",
            "schedule_days": 124,
            "schedule_time": "02:00",
        }
        for i in range(30)
    ]
    client = StubClient(
        get_responses={
            "/reports/prepatch": [{"prepatch": {"devices": devices, "total": 30}}],
            "/approvals": [approvals],
            "/policies": [policies],
            "/policystats": [[]],
        }
    )
    client.org_id = 555

    result = await get_patch_tuesday_readiness(
        cast(AutomoxClient, client),
        org_id=555,
        org_uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        detail_limit=10,
    )

    emitted = _collect_follow_up_tools(result["metadata"])
    registered = _all_registered_tool_names()
    missing = emitted - registered
    assert not missing, (
        f"compound tool dispatch points at non-registered tool name(s): {missing}. "
        f"Emitted follow_up_tools: {sorted(emitted)}. Registered surface size: {len(registered)}."
    )


@pytest.mark.asyncio
async def test_compliance_snapshot_follow_up_tools_are_registered() -> None:
    """Every `follow_up_tool` emitted by get_compliance_snapshot must be the
    name of an actually-registered tool. Regression: v1.0.27 shipped with
    `get_noncompliant_report` here, which does not resolve."""
    noncompliant_devices = [{"id": i, "name": f"nc-{i}", "groupId": 10} for i in range(30)]
    client = StubClient(
        get_responses={
            "/reports/needs-attention": [
                {"nonCompliant": {"total": 30, "devices": noncompliant_devices}}
            ],
            "/servers": [
                [
                    {"id": 200 + i, "managed": True, "status": {"policy_status": "failed"}}
                    for i in range(30)
                ]
            ],
            "/policies": [[]],
            "/policystats": [[]],
        }
    )
    client.org_id = 555

    result = await get_compliance_snapshot(
        cast(AutomoxClient, client),
        org_id=555,
        detail_limit=10,
    )

    emitted = _collect_follow_up_tools(result["metadata"])
    registered = _all_registered_tool_names()
    missing = emitted - registered
    assert not missing, (
        f"compound tool dispatch points at non-registered tool name(s): {missing}. "
        f"Emitted follow_up_tools: {sorted(emitted)}. Registered surface size: {len(registered)}."
    )
