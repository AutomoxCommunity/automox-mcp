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

# SANITIZED LIVE CAPTURE (entry 0) + spec-derived synthetic sub-type (entry 1).
#
# Entry 0 mirrors the real get_action_set_solutions payload captured from the
# live tenant 2026-06-05: solution_type 'rapid7-solution', NO solution-level
# `status` key, `solution_details` is a *dict* (not a string), `remediation_type`
# 'patch-with-worklet', per-device status observed as 'not-started' (NOT the
# spec's 'pending' example), severity observed as 'critical', and the device
# objects carry more keys than the spec example (os/details dicts, agent_status,
# device_status). All device names/custom_names and IPs are replaced with
# synthetic values (RFC-5737 TEST-NET + RFC-1918 placeholders); ids/proof/version
# strings are synthetic. No real hostname/IP/CVE-proof text is retained.
#
# Entry 1 is SPEC-DERIVED (not live — this tenant emits only rapid7-solution):
# an 'automox-patch' SolutionObject sub-type assembled from the DTO property
# definitions to exercise the alternate shape (status on devices[], a string
# solution_details, low/high severities). Severity intentionally includes a None
# (not in the spec examples) to prove the wrapper does NO normalization/coercion;
# the raw payload must pass through verbatim. If a live automox-patch capture
# later becomes available it should supersede this entry.
_SOLUTIONS = [
    {
        "id": 5001,
        "organization_id": 42,
        "solution_type": "rapid7-solution",
        "remediation_type": "patch-with-worklet",
        "solution_details": {
            "solution_id": "rapid7-sol-0001",
            "solution_type": "patch",
            "solution_summary": "Apply vendor security update for example component",
            "solution_fix": "Upgrade example-pkg to the fixed release",
        },
        "devices": [
            {
                "id": 1,
                "name": "synthetic-host-01",
                "custom_name": None,
                "ip_addrs": ["192.0.2.10"],
                "ip_addrs_private": ["10.0.0.10"],
                "status": "not-started",
                "deleted": False,
                "os": {"version": "10.0.0", "name": "Example OS", "family": "Windows"},
                "details": {"proof": "synthetic-proof-text", "last_found": "2026-06-01T00:00:00Z"},
                "agent_status": "online",
                "device_status": "active",
            },
        ],
        "vulnerabilities": [
            {
                "id": "CVE-2026-0001",
                "title": "Example library RCE",
                "summary": "Remote code execution in example library",
                "severity": "critical",
            },
        ],
    },
    {
        # SPEC-DERIVED synthetic automox-patch entry (see header comment).
        "solution_type": "automox-patch",
        "remediation_type": "patch",
        "solution_details": "Apply vendor security update",
        "devices": [
            {
                "id": 2,
                "name": "synthetic-host-02",
                "custom_name": "lab-box-beta",
                "status": "pending",
                "deleted": False,
                "ip_addrs_private": ["10.0.0.20"],
            },
        ],
        "vulnerabilities": [
            {
                "id": "CVE-2026-0002",
                "title": "Example info leak",
                "summary": "Information disclosure in example component",
                "severity": "low",
            },
            {
                "id": "CVE-2026-0003",
                "title": "Example library RCE",
                "summary": "Remote code execution in example library",
                "severity": "high",
            },
            {
                # null severity — must survive verbatim (no coercion to '')
                "id": "CVE-2026-0004",
                "title": "Example uncategorized issue",
                "summary": "Unrated finding from source",
                "severity": None,
            },
        ],
    },
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
    # The status legend documents the lifecycle vocabulary with HONEST per-value
    # provenance from the 2026-06-06 upload-to-completion poll: building -> ready,
    # with 'ready' the confirmed terminal value. 'building' was emitted live by
    # the API in the 201 create body (not just a wrapper default), and 'active'
    # is the spec example only (never reproduced live).
    status_note = result["metadata"]["field_notes"]["status"]
    assert "building" in status_note
    assert "ready" in status_note
    assert "building -> ready" in status_note  # confirmed transition order
    assert "TERMINAL" in status_note  # 'ready' is terminal
    assert "spec example value only" in status_note  # 'active'
    # The old text claimed all three were "Observed live on this tenant".
    assert "active, ready, building" not in status_note


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
    assert result["data"]["total_solutions"] == 2
    # The raw solutions payload must pass through UNCHANGED — no severity/status
    # normalization or coercion. Deep-equality against the fixture proves it.
    assert result["data"]["solutions"] == _SOLUTIONS
    # Live-captured rapid7 entry: device status 'not-started' (NOT the spec's
    # 'pending'), severity 'critical', and NO solution-level status key.
    rapid7 = result["data"]["solutions"][0]
    assert rapid7["devices"][0]["status"] == "not-started"
    assert rapid7["vulnerabilities"][0]["severity"] == "critical"
    assert "status" not in rapid7
    # Spec-derived automox-patch entry: device-level status, severities verbatim
    # including the None (proving no coercion).
    patch_entry = result["data"]["solutions"][1]
    assert patch_entry["devices"][0]["status"] == "pending"
    severities = [v["severity"] for v in patch_entry["vulnerabilities"]]
    assert severities == ["low", "high", None]

    # Legend present and keyed for the three coded fields.
    field_notes = result["metadata"]["field_notes"]
    assert "vulnerabilities[].severity" in field_notes
    assert "devices[].status" in field_notes
    assert "solutions[].status" in field_notes


@pytest.mark.asyncio
async def test_solutions_field_notes_marked_unverified() -> None:
    """Regression guard for the no-unverified-vocab rule: the severity scale is
    explicitly marked unverified-live (only 'critical' was observed, not the full
    scale/ceiling), and the device-status legend states what was vs. wasn't seen
    live rather than asserting an undocumented value space."""
    client = StubClient(
        get_responses={"/orgs/42/remediations/action-sets/1/solutions": [_SOLUTIONS]}
    )
    result = await get_action_set_solutions(
        cast(AutomoxClient, client),
        org_id=42,
        action_set_id=1,
    )
    field_notes = result["metadata"]["field_notes"]
    assert "unverified-live" in field_notes["vulnerabilities[].severity"].lower()
    # Device status legend must report the live-observed values + transition.
    # Live 2026-06-06 (#165): not-started -> in_progress, with the separator
    # inconsistency called out (hyphen vs underscore). Value set stays open.
    device_status_note = field_notes["devices[].status"]
    assert "not-started" in device_status_note
    assert "in_progress" in device_status_note
    assert "not-started -> in_progress" in device_status_note
    assert "separator inconsistency" in device_status_note.lower()
    assert "open" in device_status_note.lower()
    # solutions[].status must be flagged spec-defined but not-observed-live, and
    # note that patch-now dispatches a direct device command (no persistent policy).
    solutions_status_note = field_notes["solutions[].status"]
    assert "not-observed-live" in solutions_status_note.lower()
    assert "policy_id=0" in solutions_status_note


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
async def test_upload_submits_multipart_request() -> None:
    response = {"id": 3, "status": "building", "organization_id": 42}
    client = StubClient(post_responses={"/orgs/42/remediations/action-sets/upload": [response]})
    result = await upload_action_set(
        cast(AutomoxClient, client),
        org_id=42,
        csv_content="Hostname,CVE ID\nhost1,CVE-2021-1234",
        source="qualys",
        filename="qualys-export.csv",
    )
    assert result["data"]["id"] == 3
    assert result["data"]["status"] == "building"

    method, path, payload = client.calls[0]
    assert method == "POST_MULTIPART"
    assert path == "/orgs/42/remediations/action-sets/upload"
    # source rides the query string; format mirrors it in the body.
    assert payload["params"] == {"source": "qualys"}
    assert payload["data"] == {"format": "qualys"}
    fname, content, ctype = payload["files"]["file"]
    assert fname == "qualys-export.csv"
    assert content == b"Hostname,CVE ID\nhost1,CVE-2021-1234"
    assert ctype == "text/csv"


@pytest.mark.asyncio
async def test_upload_handles_array_response() -> None:
    # The spec types the 201 body as a one-element array; handle that shape too.
    client = StubClient(
        post_responses={
            "/orgs/42/remediations/action-sets/upload": [[{"id": 9, "status": "building"}]]
        }
    )
    result = await upload_action_set(
        cast(AutomoxClient, client),
        org_id=42,
        csv_content="a,b\n1,2",
    )
    assert result["data"]["id"] == 9


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
