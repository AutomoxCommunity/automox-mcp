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


def test_highest_patch_severity_all_no_known_cves_not_unknown() -> None:
    """Finding 31 witness: an all-no_known_cves device reports 'no_known_cves'.

    This must NOT collapse to 'unknown' — the two are distinct states (a patch
    with no associated CVE vs. severity absent/undetermined). Live-verified
    2026-06-05 that the upstream payload carries 'no_known_cves' as a severity.
    """
    patches = [{"severity": "no_known_cves"}, {"severity": "no_known_cves"}]
    assert _highest_patch_severity(patches) == "no_known_cves"


def test_highest_patch_severity_spec_unknown_value_returns_unknown() -> None:
    """The spec literal 'unknown' severity returns 'unknown' (rank below no_known_cves)."""
    patches = [{"severity": "unknown"}]
    assert _highest_patch_severity(patches) == "unknown"


def test_highest_patch_severity_no_known_cves_outranks_unknown() -> None:
    """A mix of no_known_cves and unknown reports 'no_known_cves' (it ranks higher)."""
    patches = [{"severity": "unknown"}, {"severity": "no_known_cves"}]
    assert _highest_patch_severity(patches) == "no_known_cves"


def test_highest_patch_severity_none_outranks_no_known_cves() -> None:
    """Chosen ordering: spec value 'none' (rank 0) ranks above 'no_known_cves' (-1)."""
    patches = [{"severity": "no_known_cves"}, {"severity": "none"}]
    assert _highest_patch_severity(patches) == "none"


def test_highest_patch_severity_none_string_survives_or_chain() -> None:
    """A truthy string 'none' must NOT fall through the `or` chain to 'unknown'.

    Guards against a future refactor fumbling the truthy-string handling: 'none'
    is a truthy string, so it survives `severity or cve_severity or ''` and must
    rank as the spec 'none' value, not the absent-data 'unknown' bucket.
    """
    assert _highest_patch_severity([{"severity": "none"}]) == "none"


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
    """Auto-pagination issues multiple GETs and terminates on the first empty page."""
    page1_devices = [{"id": i, "name": f"host{i}", "patches": []} for i in range(1, 4)]
    page2_devices = [{"id": 4, "name": "host4", "patches": []}]

    page1_response = {"prepatch": {"total": 4, "devices": page1_devices}}
    page2_response = {"prepatch": {"total": 4, "devices": page2_devices}}
    # Pagination stops when a page returns no devices.
    page3_response = {"prepatch": {"total": 4, "devices": []}}

    client = StubClient(
        get_responses={"/reports/prepatch": [page1_response, page2_response, page3_response]},
    )

    result = await get_prepatch_report(
        cast(AutomoxClient, client),
        org_id=42,
    )

    assert result["data"]["total_devices"] == 4
    get_calls = [c for c in client.calls if c[0] == "GET"]
    assert len(get_calls) == 3

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


# Captured & sanitized live prepatch shape (2026-06-05). Device keys and patch
# keys mirror the live payload; severities include 'no_known_cves' alongside an
# assessed value, and the summary carries the live bucket set
# {total, needsAttention, none, low, medium, high, critical, no_known_cves,
# unknown}. The per-severity buckets intentionally do NOT sum to summary['total']
# (live: total=54 vs bucket sum=36) — this keeps the total_pending_patches caveat
# honest and prevents a future 'sum==total' assertion from creeping back in.
_LIVE_PREPATCH_RESPONSE: dict[str, Any] = {
    "prepatch": {
        "total": 54,
        "needsAttention": 5,
        "none": 0,
        "low": 0,
        "medium": 0,
        "high": 1,
        "critical": 3,
        "no_known_cves": 0,
        "unknown": 32,
        "devices": [
            {
                "id": 1001,
                "name": "device-a",
                "group": "Default Group",
                "os_family": "Windows",
                "connected": True,
                "compliant": True,
                "needsReboot": False,
                "createTime": "2025-01-01T00:00:00Z",
                "patches": [
                    {
                        "id": 5001,
                        "name": "patch-a1",
                        "severity": "no_known_cves",
                        "cve": None,
                        "needsApproval": False,
                        "packageVersionId": 9001,
                        "createTime": "2025-01-01T00:00:00Z",
                        "patchTime": "2025-01-02T00:00:00Z",
                    },
                    {
                        "id": 5002,
                        "name": "patch-a2",
                        "severity": "no_known_cves",
                        "cve": None,
                        "needsApproval": False,
                        "packageVersionId": 9002,
                        "createTime": "2025-01-01T00:00:00Z",
                        "patchTime": "2025-01-02T00:00:00Z",
                    },
                ],
            },
            {
                "id": 1002,
                "name": "device-b",
                "group": "Default Group",
                "os_family": "Windows",
                "connected": True,
                "compliant": False,
                "needsReboot": True,
                "createTime": "2025-01-01T00:00:00Z",
                "patches": [
                    {
                        "id": 5003,
                        "name": "patch-b1",
                        "severity": "critical",
                        "cve": "CVE-0000-0000",
                        "needsApproval": True,
                        "packageVersionId": 9003,
                        "createTime": "2025-01-01T00:00:00Z",
                        "patchTime": None,
                    },
                ],
            },
            {
                "id": 1003,
                "name": "device-c",
                "group": "Default Group",
                "os_family": "Linux",
                "connected": True,
                "compliant": True,
                "needsReboot": False,
                "createTime": "2025-01-01T00:00:00Z",
                "patches": [],
            },
        ],
    }
}


@pytest.mark.asyncio
async def test_get_prepatch_report_live_shape_separates_no_known_cves() -> None:
    """Integration witness for finding 31 against a captured live shape.

    The all-no_known_cves device projects highest_severity == 'no_known_cves'
    (NOT 'unknown'); the recomputed summary carries a distinct no_known_cves
    bucket; the raw upstream summary is passed through unmodified under
    api_summary; and metadata.field_notes documents the semantics.
    """
    client = StubClient(get_responses={"/reports/prepatch": [_LIVE_PREPATCH_RESPONSE]})

    result = await get_prepatch_report(cast(AutomoxClient, client), org_id=42, limit=500)
    data = result["data"]

    by_id = {d["server_id"]: d for d in data["devices"]}
    # All-no_known_cves device must not collapse to 'unknown'.
    assert by_id[1001]["highest_severity"] == "no_known_cves"
    assert by_id[1002]["highest_severity"] == "critical"
    # Empty patches → 'unknown'.
    assert by_id[1003]["highest_severity"] == "unknown"

    summary = data["summary"]
    # Recomputed summary has a distinct no_known_cves bucket counted separately.
    assert summary["no_known_cves"] == 1
    assert summary["unknown"] == 1
    assert summary["critical"] == 1

    # Raw upstream summary passes through unmodified, with both raw buckets.
    api_summary = data["api_summary"]
    assert api_summary["no_known_cves"] == 0
    assert api_summary["unknown"] == 32
    assert api_summary["total"] == 54

    # total_pending_patches is the upstream relabel; buckets do NOT sum to it.
    assert data["total_pending_patches"] == 54
    bucket_sum = sum(
        summary[k]
        for k in ("critical", "high", "medium", "low", "none", "no_known_cves", "unknown")
    )
    assert bucket_sum != data["total_pending_patches"]

    notes = result["metadata"]["field_notes"]
    assert "highest_severity" in notes
    assert "compliant" in notes
    assert "total_pending_patches" in notes


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


@pytest.mark.asyncio
async def test_get_prepatch_report_total_is_pending_patches_not_devices() -> None:
    """The API's `total` field counts pending patches, not devices.

    Regression test for #28. The response field is `total_pending_patches`
    (matching the underlying value), not `total_org_devices`.
    """
    # 2 devices with a combined 7 pending patches → API reports total=7.
    devices = [
        {"id": 1, "name": "host1", "patches": [{"severity": "high"}] * 4},
        {"id": 2, "name": "host2", "patches": [{"severity": "low"}] * 3},
    ]
    response = {"prepatch": {"total": 7, "devices": devices}}
    client = StubClient(get_responses={"/reports/prepatch": [response]})

    result = await get_prepatch_report(cast(AutomoxClient, client), org_id=42, limit=500)

    data = result["data"]
    # `total_pending_patches` reflects the API's total verbatim.
    assert data["total_pending_patches"] == 7
    assert data["summary"]["total_pending_patches"] == 7
    # `total_devices` is the count of devices in this report (devices needing patches).
    assert data["total_devices"] == 2
    # The mislabeled key from prior versions is gone.
    assert "total_org_devices" not in data
    assert "total_org_devices" not in data["summary"]


@pytest.mark.asyncio
async def test_get_prepatch_report_pagination_does_not_short_circuit_on_total() -> None:
    """Pagination must not terminate based on `summary.total` (which is patch count, not devices).

    Regression test for #28: if `total` (patches) is small relative to actual
    device count, the loop must continue until an empty page is returned.
    """
    # First page returns 2 devices; API reports total=2 (patches), but more devices exist.
    page1 = {
        "prepatch": {
            "total": 2,
            "devices": [{"id": 1, "name": "h1", "patches": [{"severity": "high"}]}],
        }
    }
    page2 = {
        "prepatch": {
            "total": 2,
            "devices": [{"id": 2, "name": "h2", "patches": [{"severity": "low"}]}],
        }
    }
    page3 = {"prepatch": {"total": 2, "devices": []}}  # empty page → terminate
    client = StubClient(
        get_responses={"/reports/prepatch": [page1, page2, page3]},
    )

    result = await get_prepatch_report(cast(AutomoxClient, client), org_id=42)

    get_calls = [c for c in client.calls if c[0] == "GET"]
    # Three calls means we kept paginating past `total`, then stopped on empty page.
    assert len(get_calls) == 3
    assert result["data"]["total_devices"] == 2


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


# Captured & sanitized live needs-attention policy shape (2026-06-05). Live
# reasonForFail is a verbose multi-line log blob (~600-840 chars) containing
# third-party app names and ISO timestamps; replaced here with neutral
# placeholder text long enough to exceed the 2000-char truncation cap.
_LONG_REASON = (
    "Patch installation could not complete on the target device. "
    "Step output follows: " + ("placeholder remediation log line. " * 80)
)


@pytest.mark.asyncio
async def test_get_noncompliant_report_failing_policy_fields_surfaced() -> None:
    """Finding 33: each failing policy carries type, severity, reason_for_fail, package_count.

    Fixture mirrors the captured live policy object shape (keys id, name,
    packages, policyCreateTime, reasonForFail, severity, type).
    """
    device = {
        "id": 20,
        "customName": "device-with-failures",
        "policies": [
            {
                "id": 101,
                "name": "Policy A",
                "type": "patch",
                "severity": "unknown",
                "reasonForFail": "short failure reason",
                "packages": [{"id": 1}, {"id": 2}],
                "policyCreateTime": "2025-01-01T00:00:00Z",
            },
        ],
    }
    client = StubClient(
        get_responses={"/reports/needs-attention": [_make_noncompliant_response([device])]},
    )

    result = await get_noncompliant_report(cast(AutomoxClient, client), org_id=42)

    pol = result["data"]["devices"][0]["failing_policies"][0]
    assert pol["id"] == 101
    assert pol["name"] == "Policy A"
    assert pol["type"] == "patch"
    assert pol["severity"] == "unknown"
    assert pol["reason_for_fail"] == "short failure reason"
    assert pol["package_count"] == 2

    notes = result["metadata"]["field_notes"]
    assert "reason_for_fail" in notes
    assert "severity" in notes
    assert "type" in notes


@pytest.mark.asyncio
async def test_get_noncompliant_report_reason_for_fail_truncated() -> None:
    """A long reasonForFail is truncated with a marker; a short one passes through."""
    device = {
        "id": 21,
        "name": "long-reason-device",
        "policies": [
            {"id": 201, "name": "Long", "reasonForFail": _LONG_REASON, "packages": None},
            {"id": 202, "name": "Short", "reasonForFail": "ok", "packages": []},
        ],
    }
    client = StubClient(
        get_responses={"/reports/needs-attention": [_make_noncompliant_response([device])]},
    )

    result = await get_noncompliant_report(cast(AutomoxClient, client), org_id=42)
    pols = {p["id"]: p for p in result["data"]["devices"][0]["failing_policies"]}

    assert len(_LONG_REASON) > 2000
    long_reason = pols[201]["reason_for_fail"]
    assert long_reason.startswith(_LONG_REASON[:2000])
    assert "... [truncated" in long_reason
    assert f"[truncated {len(_LONG_REASON) - 2000} chars]" in long_reason
    # packages=None → package_count None
    assert pols[201]["package_count"] is None

    # Short reason passes through verbatim; empty list → count 0.
    assert pols[202]["reason_for_fail"] == "ok"
    assert pols[202]["package_count"] == 0


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


@pytest.mark.asyncio
async def test_get_noncompliant_report_paginates_when_total_equals_page_size() -> None:
    """Regression for issue #68 — verified against a live tenant on 2026-05-27.

    On /reports/needs-attention the API's ``summary["total"]`` is the
    **per-page device count**, not the total fleet device count. A 138-device
    tenant paginated at limit=10 returned ``summary.total == 10`` on every
    page. The previous code terminated the loop when
    ``len(device_list) >= summary.total`` — which fires after page 0 with the
    page-size value, dropping every subsequent page.

    The bug only triggers in the workflow's auto-pagination path (no explicit
    limit), so the test must not pass ``limit`` either. The workflow's
    hardcoded page size is 500, so we need at least one full page plus a
    short page to exercise the multi-page loop.
    """
    # 600 devices total → two pages: 500, then 100 (short page terminates loop).
    all_devices = [{"id": i, "name": f"device-{i}"} for i in range(600)]
    workflow_page_size = 500  # matches the hardcoded value in get_noncompliant_report
    pages = [
        # Each page reports summary.total == this page's device count, matching
        # the upstream API behavior observed in the live-tenant probe.
        {
            "nonCompliant": {
                "total": len(all_devices[i : i + workflow_page_size]),
                "devices": all_devices[i : i + workflow_page_size],
            }
        }
        for i in range(0, len(all_devices), workflow_page_size)
    ]

    client = StubClient(get_responses={"/reports/needs-attention": pages})

    # No explicit limit — exercises the auto-paginate path where the bug fired.
    result = await get_noncompliant_report(cast(AutomoxClient, client), org_id=42)

    # All 600 devices must be returned across both pages — the early-break
    # on summary.total would have cut this off at 500.
    assert len(result["data"]["devices"]) == 600
    assert result["data"]["total_devices"] == 600
    # The workflow terminates on the first empty page, so a third request
    # (offset=1000, returns no devices) is expected.
    assert len(client.calls) >= 2


@pytest.mark.asyncio
async def test_get_noncompliant_report_total_devices_reflects_actual_count() -> None:
    """``data.total_devices`` must reflect the accumulated device count, not
    ``summary["total"]`` (which is per-page on /reports/needs-attention).
    """
    devices = [{"id": i} for i in range(15)]
    response = {
        "nonCompliant": {
            # Mimic the live tenant: total == page size, not total devices.
            "total": 15,
            "devices": devices,
        }
    }
    client = StubClient(get_responses={"/reports/needs-attention": [response]})

    result = await get_noncompliant_report(
        cast(AutomoxClient, client),
        org_id=42,
        limit=500,
    )

    # 15 devices in, 15 reported back — independent of whatever summary.total said.
    assert result["data"]["total_devices"] == 15


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
