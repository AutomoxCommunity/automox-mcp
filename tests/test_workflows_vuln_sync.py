"""Tests for vulnerability sync / remediations workflows."""

from typing import cast

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.vuln_sync import (
    get_action_set_detail,
    get_action_set_issues,
    get_action_set_solutions,
    get_upload_formats,
    list_remediation_action_sets,
    upload_action_set,
)

# Fixture shape mirrors the actual /orgs/{org}/remediations/action-sets
# response: a `source` object with `name`/`type`, plus a nested
# `statistics` block holding per-bucket counts. The summarizer flattens
# this into a top-level `name`, `issue_count`, `solution_count`, etc.
_ACTION_SETS = [
    {
        "id": 1,
        "configuration_id": "11111111-1111-1111-1111-111111111111",
        "organization_id": 42,
        "status": "completed",
        "source": {"name": "Qualys Import Q1", "type": "Qualys"},
        "statistics": {
            "issues": {"unknown-host": {"count": 50}},
            "solutions": {
                "patch-now": {"count": 12, "device_count": 5, "vulnerability_count": 30},
                "patch-with-worklet": {"count": 8, "device_count": 3, "vulnerability_count": 20},
            },
            "devices": {"matched_count": 5},
        },
        "created_at": "2026-01-15T00:00:00Z",
        "updated_at": "2026-01-16T00:00:00Z",
        "error": None,
    },
    {
        "id": 2,
        "configuration_id": "22222222-2222-2222-2222-222222222222",
        "organization_id": 42,
        "status": "pending",
        "source": {"name": "Tenable Import", "type": "Tenable"},
    },
]

_ACTION_SET_DETAIL = {
    "id": 1,
    "configuration_id": "11111111-1111-1111-1111-111111111111",
    "organization_id": 42,
    "status": "completed",
    "source": {"name": "Qualys Import Q1", "type": "Qualys"},
    "statistics": {
        "issues": {"unknown-host": {"count": 50}},
        "solutions": {
            "patch-now": {"count": 30, "device_count": 5, "vulnerability_count": 30},
        },
        "devices": {"matched_count": 5},
    },
    "created_at": "2026-01-15T00:00:00Z",
    "updated_at": "2026-01-16T00:00:00Z",
    "error": None,
}

_ISSUES = [
    {"id": 201, "cve_id": "CVE-2026-0001", "severity": "critical", "title": "OpenSSL vuln"},
    {"id": 202, "cve_id": "CVE-2026-0002", "severity": "high", "title": "Curl vuln"},
]

_SOLUTIONS = [
    {"id": 301, "title": "Update OpenSSL to 3.2.0", "action_count": 5},
]

_FORMATS = [
    {"name": "qualys", "description": "Qualys CSV export format"},
    {"name": "tenable", "description": "Tenable CSV export format"},
]


# ---------------------------------------------------------------------------
# list_remediation_action_sets
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_action_sets_returns_summaries() -> None:
    client = StubClient(get_responses={"/orgs/42/remediations/action-sets": [_ACTION_SETS]})
    result = await list_remediation_action_sets(cast(AutomoxClient, client), org_id=42)

    assert result["data"]["total_action_sets"] == 2
    assert result["data"]["action_sets"][0]["name"] == "Qualys Import Q1"
    assert result["data"]["action_sets"][0]["issue_count"] == 50


@pytest.mark.asyncio
async def test_list_action_sets_empty() -> None:
    client = StubClient(get_responses={"/orgs/42/remediations/action-sets": [[]]})
    result = await list_remediation_action_sets(cast(AutomoxClient, client), org_id=42)
    assert result["data"]["total_action_sets"] == 0


# ---------------------------------------------------------------------------
# get_action_set_detail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detail_returns_info() -> None:
    """Bug #4a from issue #43: the detail endpoint used to return only
    the same minimal 5 keys as the list summary because the summarizer
    looked for top-level fields the API doesn't emit. After the fix the
    detail surfaces the nested `statistics` counts (issue_count,
    solution_count, matched_device_count) and pulls `name` out of the
    `source` object."""
    client = StubClient(get_responses={"/orgs/42/remediations/action-sets/1": [_ACTION_SET_DETAIL]})
    result = await get_action_set_detail(
        cast(AutomoxClient, client),
        org_id=42,
        action_set_id=1,
    )
    detail = result["data"]
    assert detail["id"] == 1
    assert detail["configuration_id"] == "11111111-1111-1111-1111-111111111111"
    assert detail["name"] == "Qualys Import Q1"
    assert detail["issue_count"] == 50
    assert detail["solution_count"] == 30
    assert detail["matched_device_count"] == 5
    # Raw statistics block exposed for callers that need per-bucket detail
    assert "issues" in detail["statistics"]
    assert "solutions" in detail["statistics"]


# ---------------------------------------------------------------------------
# get_action_set_issues
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_issues_returns_list() -> None:
    client = StubClient(get_responses={"/orgs/42/remediations/action-sets/1/issues": [_ISSUES]})
    result = await get_action_set_issues(
        cast(AutomoxClient, client),
        org_id=42,
        action_set_id=1,
    )
    assert result["data"]["total_issues"] == 2
    assert result["data"]["issues"][0]["cve_id"] == "CVE-2026-0001"


# ---------------------------------------------------------------------------
# get_action_set_solutions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_solutions_returns_list() -> None:
    client = StubClient(
        get_responses={"/orgs/42/remediations/action-sets/1/solutions": [_SOLUTIONS]}
    )
    result = await get_action_set_solutions(
        cast(AutomoxClient, client),
        org_id=42,
        action_set_id=1,
    )
    assert result["data"]["total_solutions"] == 1


# ---------------------------------------------------------------------------
# get_upload_formats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_formats_returns_list() -> None:
    client = StubClient(
        get_responses={"/orgs/42/remediations/action-sets/upload/formats": [_FORMATS]}
    )
    result = await get_upload_formats(cast(AutomoxClient, client), org_id=42)
    assert result["data"]["total_formats"] == 2


# ---------------------------------------------------------------------------
# upload_action_set
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_submits_request() -> None:
    response = {"id": 3, "status": "pending"}
    client = StubClient(post_responses={"/orgs/42/remediations/action-sets/upload": [response]})
    result = await upload_action_set(
        cast(AutomoxClient, client),
        org_id=42,
        action_set_data={"format": "qualys", "csv_data": "..."},
    )
    assert result["data"]["id"] == 3
    assert result["data"]["status"] == "pending"
    assert client.calls[0][0] == "POST"
