"""Tests for vulnerability sync / remediations workflows."""

from typing import cast

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.vuln_sync import (
    apply_remediation_actions,
    delete_action_set,
    delete_action_sets_bulk,
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


# ---------------------------------------------------------------------------
# apply_remediation_actions (issue #91 category C, gated execution)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_remediation_actions_maps_to_camelcase_body() -> None:
    path = "/orgs/42/remediations/action-sets/7/actions"
    client = StubClient(post_responses={path: [{}]})
    result = await apply_remediation_actions(
        cast(AutomoxClient, client),
        org_id=42,
        action_set_id=7,
        actions=[
            {"action": "patch-now", "solution_id": 555, "devices": [1, 2]},
            {
                "action": "patch-with-worklet",
                "solution_id": 556,
                "devices": [3],
                "worklet_id": 99,
            },
        ],
    )
    assert result["data"]["actions_submitted"] == 2
    assert result["data"]["total_device_targets"] == 3
    assert result["data"]["status"] == "accepted"

    method, called_path, body = client.calls[0]
    assert method == "POST"
    assert called_path == path
    # snake_case -> camelCase mapping for the API body
    assert body["actions"][0] == {"action": "patch-now", "solutionId": 555, "devices": [1, 2]}
    assert body["actions"][1]["workletId"] == 99


def test_run_remediation_params_validation() -> None:
    from pydantic import ValidationError

    from automox_mcp.schemas import RunRemediationActionsParams

    base = {"org_id": 42, "action_set_id": 7}
    # bad action verb
    with pytest.raises(ValidationError, match="patch-now"):
        RunRemediationActionsParams(
            **base, actions=[{"action": "nope", "solution_id": 1, "devices": [1]}]
        )
    # missing solution_id
    with pytest.raises(ValidationError, match="solution_id"):
        RunRemediationActionsParams(**base, actions=[{"action": "patch-now", "devices": [1]}])
    # empty devices
    with pytest.raises(ValidationError, match="devices"):
        RunRemediationActionsParams(
            **base, actions=[{"action": "patch-now", "solution_id": 1, "devices": []}]
        )
    # patch-with-worklet requires worklet_id
    with pytest.raises(ValidationError, match="worklet_id"):
        RunRemediationActionsParams(
            **base,
            actions=[{"action": "patch-with-worklet", "solution_id": 1, "devices": [1]}],
        )


def test_apply_remediation_tool_gated_by_env(monkeypatch) -> None:
    from conftest import FakeClient, StubServer

    from automox_mcp.tools import vuln_sync_tools

    # default off -> not registered
    monkeypatch.delenv("AUTOMOX_MCP_ALLOW_APPLY_REMEDIATION_ACTIONS", raising=False)
    off = StubServer()
    vuln_sync_tools.register(off, read_only=False, client=FakeClient())
    assert "apply_remediation_actions" not in off.tools

    # explicit opt-in -> registered
    monkeypatch.setenv("AUTOMOX_MCP_ALLOW_APPLY_REMEDIATION_ACTIONS", "true")
    on = StubServer()
    vuln_sync_tools.register(on, read_only=False, client=FakeClient())
    assert "apply_remediation_actions" in on.tools

    # read-only mode never registers it, even with the env flag on
    ro = StubServer()
    vuln_sync_tools.register(ro, read_only=True, client=FakeClient())
    assert "apply_remediation_actions" not in ro.tools


@pytest.mark.asyncio
async def test_delete_action_set_calls_endpoint() -> None:
    client = StubClient()
    result = await delete_action_set(cast(AutomoxClient, client), org_id=42, action_set_id=7)
    assert ("DELETE", "/orgs/42/remediations/action-sets/7", None) in client.calls
    assert result["data"] == {"action_set_id": 7, "deleted": True}
    assert result["metadata"]["org_id"] == 42


@pytest.mark.asyncio
async def test_delete_action_sets_bulk_single_atomic_call() -> None:
    client = StubClient()
    result = await delete_action_sets_bulk(
        cast(AutomoxClient, client), org_id=42, action_set_ids=[1, 2, 3]
    )
    deletes = [c for c in client.calls if c[0] == "DELETE"]
    # Exactly one round-trip to the native bulk endpoint with an `ids` body.
    assert len(deletes) == 1
    method, path, body = deletes[0]
    assert path == "/orgs/42/remediations/action-sets"
    assert body == {"ids": [1, 2, 3]}
    assert result["data"]["deleted_count"] == 3
    assert result["data"]["deleted"] == [1, 2, 3]
    assert result["data"]["requested"] == 3
