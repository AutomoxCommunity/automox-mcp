"""Tests for compound workflows (get_patch_tuesday_readiness, get_compliance_snapshot)."""

import copy
from typing import Any, cast

import pytest

from automox_mcp.client import AutomoxAPIError, AutomoxClient
from automox_mcp.workflows.compound import (
    get_compliance_snapshot,
    get_patch_tuesday_readiness,
)


class StubClient:
    """Lightweight Automox client stub for compound workflow testing."""

    def __init__(
        self,
        *,
        get_responses: dict[str, list[Any]] | None = None,
        post_responses: dict[str, list[Any]] | None = None,
    ) -> None:
        self._get_responses = {key: list(value) for key, value in (get_responses or {}).items()}
        self._post_responses = {key: list(value) for key, value in (post_responses or {}).items()}
        self.org_id: int | None = 555
        self.org_uuid: str | None = None
        self.account_uuid: str = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    async def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        self.calls.append(("GET", path, params))
        responses = self._get_responses.get(path)
        if not responses:
            # Return empty response for unmatched paths (graceful degradation)
            return {}
        return copy.deepcopy(responses.pop(0))


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
    return StubClient(
        get_responses={
            "/reports/prepatch": [_PREPATCH_RESPONSE],
            "/approvals": [_APPROVALS_RESPONSE],
            "/policies": [_POLICIES_RESPONSE],
            "/policystats": [_POLICYSTATS_RESPONSE],
        }
    )


def _build_compliance_client() -> StubClient:
    return StubClient(
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
    result = await get_patch_tuesday_readiness(
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
                [{"id": 1, "managed": True, "status": {"policy_status": "success"}, "last_check_in": "2025-03-18T12:00:00Z"}]
            ],
            "/policies": [_POLICIES_RESPONSE],
            "/policystats": [_POLICYSTATS_RESPONSE],
        }
    )

    result = await get_compliance_snapshot(
        cast(AutomoxClient, client),
        org_id=555,
    )

    errors = result["metadata"].get("errors")
    assert errors is not None
    assert any("noncompliant" in e for e in errors)
    # Policy summary should still be populated
    assert result["data"]["policy_summary"]["total_policies"] > 0
