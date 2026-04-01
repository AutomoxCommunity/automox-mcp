"""Tests for vulnerability sync / remediations workflows."""

from typing import cast

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.vuln_sync import (
    get_action_set_actions,
    get_action_set_detail,
    get_action_set_issues,
    get_action_set_solutions,
    get_upload_formats,
    list_remediation_action_sets,
    upload_action_set,
)

_ACTION_SETS = [
    {
        "id": 1,
        "name": "Qualys Import Q1",
        "status": "completed",
        "source": "qualys",
        "created_at": "2026-01-15T00:00:00Z",
        "issue_count": 50,
        "action_count": 30,
        "solution_count": 20,
    },
    {
        "id": 2,
        "name": "Tenable Import",
        "status": "pending",
        "source": "tenable",
    },
]

_ACTION_SET_DETAIL = {
    "id": 1,
    "name": "Qualys Import Q1",
    "status": "completed",
    "source": "qualys",
    "issue_count": 50,
    "action_count": 30,
}

_ACTIONS = [
    {"id": 101, "type": "patch", "package_name": "openssl", "severity": "critical"},
    {"id": 102, "type": "patch", "package_name": "curl", "severity": "high"},
]

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
    client = StubClient(get_responses={"/orgs/42/remediations/action-sets/1": [_ACTION_SET_DETAIL]})
    result = await get_action_set_detail(
        cast(AutomoxClient, client),
        org_id=42,
        action_set_id=1,
    )
    assert result["data"]["id"] == 1
    assert result["data"]["action_count"] == 30


# ---------------------------------------------------------------------------
# get_action_set_actions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_actions_returns_list() -> None:
    client = StubClient(get_responses={"/orgs/42/remediations/action-sets/1/actions": [_ACTIONS]})
    result = await get_action_set_actions(
        cast(AutomoxClient, client),
        org_id=42,
        action_set_id=1,
    )
    assert result["data"]["total_actions"] == 2
    assert result["data"]["action_set_id"] == 1


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
