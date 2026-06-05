"""Tests for policy history v2 workflows."""

from typing import Any, cast

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.policy_history import (
    get_policy_history_detail,
    get_policy_run_detail_v2,
    get_policy_runs_for_policy,
    list_policy_execution_counts,
    list_policy_runs_v2,
    policy_run_count,
    policy_runs_by_policy,
)

_ORG_UUID = "11111111-2222-3333-4444-555555555555"

# Captured shape (sanitized) from /policy-history/policy-runs (live 2026-06-05):
# every run carries `device_count`, and the per-outcome device counts sum to it
# exactly (probe: 8 runs, dc in {41,168,207}, outcomes summed to device_count
# with 0 mismatches). The projection surfaces device_count and the legend
# asserts "outcomes sum to device_count", so the fixture must carry it or that
# load-bearing field goes untested.
_POLICY_RUNS = [
    {
        "policy_uuid": "pol-001",
        "policy_id": 101,
        "org_uuid": _ORG_UUID,
        "policy_name": "Patch All",
        "policy_type": "patch",
        "pending": 0,
        "success": 9,
        "remediation_not_applicable": 0,
        "failed": 1,
        "not_included": 0,
        "run_time": "2026-03-01T00:00:00Z",
        "execution_token": "exec-001",
        "run_count": 10,
        "device_count": 10,  # 0+9+0+1+0
    },
    {
        "policy_uuid": "pol-002",
        "policy_id": 102,
        "org_uuid": _ORG_UUID,
        "policy_name": "Custom Script",
        "policy_type": "custom",
        "pending": 2,
        "success": 3,
        "remediation_not_applicable": 0,
        "failed": 0,
        "not_included": 0,
        "run_time": "2026-03-01T01:00:00Z",
        "execution_token": "exec-002",
        "device_count": 5,  # 2+3+0+0+0
    },
]

_RUN_DETAIL_RESULTS = [
    {"device_name": "host-1", "result_status": "success"},
    {"device_name": "host-2", "result_status": "failure"},
]

_POLICY_HISTORY = {
    "uuid": "pol-001",
    "id": 101,
    "org_uuid": _ORG_UUID,
    "name": "Patch All",
    "type": "patch",
    "deleted_at": None,
    "updated_at": "2026-03-01T00:00:00Z",
    "last_run_time": "2026-03-01T01:00:00Z",
}


def _make_client(**kwargs: Any) -> StubClient:
    """Create a StubClient with org_uuid pre-set to skip resolution."""
    client = StubClient(**kwargs)
    client.org_uuid = _ORG_UUID
    return client


# ---------------------------------------------------------------------------
# list_policy_runs_v2
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_runs_returns_summaries() -> None:
    client = _make_client(get_responses={"/policy-history/policy-runs": [_POLICY_RUNS]})
    result = await list_policy_runs_v2(cast(AutomoxClient, client), org_id=42)

    assert result["data"]["total_runs"] == 2
    assert result["data"]["runs"][0]["policy_uuid"] == "pol-001"
    # Outcome counts are devices-per-outcome, grouped so they can't be
    # misread as run statuses.
    assert result["data"]["runs"][0]["device_outcomes"]["success"] == 9
    assert "success" not in result["data"]["runs"][0]
    # device_count is surfaced and the per-outcome device counts sum to it,
    # exactly as live (the legend asserts this — exercise it, don't just claim).
    for run in result["data"]["runs"]:
        assert "device_count" in run
        outcome_sum = sum(v for v in run["device_outcomes"].values() if isinstance(v, (int, float)))
        assert outcome_sum == run["device_count"]


@pytest.mark.asyncio
async def test_list_runs_filters_client_side() -> None:
    """The upstream policy-report-api silently ignores filter query params,
    so the workflow fetches a large window and filters locally. The HTTP
    call must NOT pass the filter params (they would be noise on the
    wire), and the upstream `limit` is bumped to the pool size."""
    client = _make_client(get_responses={"/policy-history/policy-runs": [_POLICY_RUNS]})
    result = await list_policy_runs_v2(
        cast(AutomoxClient, client),
        org_id=42,
        policy_type="patch",
        limit=10,
        page=0,
    )

    _, _path, params = client.calls[0]
    # Filter params must not be forwarded upstream.
    assert "policy_type" not in params
    assert "policy_name" not in params
    assert "result_status" not in params
    assert "start_time" not in params
    # Upstream is asked for the full pool when filtering client-side.
    assert params["limit"] == 5000
    # Only the patch run survives the filter.
    runs = result["data"]["runs"]
    assert len(runs) == 1
    assert runs[0]["policy_type"] == "patch"
    assert result["metadata"]["filter_strategy"] == "client_side"
    assert result["metadata"]["filters_applied"] == {"policy_type": "patch"}
    assert result["metadata"]["filtered_count"] == 1
    assert result["metadata"]["pagination"]["has_more"] is False


@pytest.mark.asyncio
async def test_list_runs_passes_pagination_when_unfiltered() -> None:
    """Without filters, upstream pagination is honored — page/limit pass through."""
    client = _make_client(get_responses={"/policy-history/policy-runs": [_POLICY_RUNS]})
    await list_policy_runs_v2(
        cast(AutomoxClient, client),
        org_id=42,
        page=2,
        limit=25,
    )

    _, _path, params = client.calls[0]
    assert params["page"] == 2
    assert params["limit"] == 25


@pytest.mark.asyncio
async def test_list_runs_filters_by_policy_name_substring() -> None:
    runs = [
        {"policy_uuid": "p1", "policy_name": "Patch All Devices", "policy_type": "patch"},
        {"policy_uuid": "p2", "policy_name": "Custom Worklet", "policy_type": "custom"},
        {"policy_uuid": "p3", "policy_name": "Patch Linux", "policy_type": "patch"},
    ]
    client = _make_client(get_responses={"/policy-history/policy-runs": [runs]})
    result = await list_policy_runs_v2(
        cast(AutomoxClient, client),
        org_id=42,
        policy_name="patch",
    )
    names = sorted(r["policy_name"] for r in result["data"]["runs"])
    assert names == ["Patch All Devices", "Patch Linux"]


@pytest.mark.asyncio
async def test_list_runs_filters_result_status_by_counter() -> None:
    """result_status="failed" should include only runs with non-zero `failed`."""
    runs = [
        {"policy_uuid": "p1", "policy_name": "A", "failed": 0, "success": 10},
        {"policy_uuid": "p2", "policy_name": "B", "failed": 3, "success": 7},
    ]
    client = _make_client(get_responses={"/policy-history/policy-runs": [runs]})
    result = await list_policy_runs_v2(
        cast(AutomoxClient, client),
        org_id=42,
        result_status="failed",
    )
    assert len(result["data"]["runs"]) == 1
    assert result["data"]["runs"][0]["policy_uuid"] == "p2"


@pytest.mark.asyncio
async def test_list_runs_client_pagination_slices_filtered_results() -> None:
    runs = [
        {"policy_uuid": f"p{i}", "policy_name": f"name-{i}", "policy_type": "custom"}
        for i in range(25)
    ]
    client = _make_client(get_responses={"/policy-history/policy-runs": [runs]})
    result = await list_policy_runs_v2(
        cast(AutomoxClient, client),
        org_id=42,
        policy_type="custom",
        limit=10,
        page=1,
    )
    returned = [r["policy_uuid"] for r in result["data"]["runs"]]
    assert returned == [f"p{i}" for i in range(10, 20)]
    pagination = result["metadata"]["pagination"]
    # Canonical fields (#52) plus legacy aliases retained for backwards-compat.
    assert pagination["page"] == 1
    assert pagination["page_size"] == 10
    assert pagination["total_elements"] == 25
    assert pagination["total_pages"] == 3
    assert pagination["has_more"] is True
    assert pagination["limit"] == 10
    assert pagination["total_count"] == 25
    # #76: emit next_page so the LLM doesn't have to derive it from page+1.
    assert pagination["next_page"] == 2
    suggested = result["metadata"]["suggested_next_call"]
    assert suggested["tool"] == "policy_runs_v2"
    assert suggested["args"]["page"] == 2
    assert suggested["args"]["limit"] == 10
    assert suggested["args"]["policy_type"] == "custom"


@pytest.mark.asyncio
async def test_list_runs_last_page_omits_next_page_hints() -> None:
    """#76: when has_more=False, neither next_page nor suggested_next_call
    should appear — the LLM must know there's nothing more to fetch."""
    runs = [
        {"policy_uuid": f"p{i}", "policy_name": f"name-{i}", "policy_type": "custom"}
        for i in range(15)
    ]
    client = _make_client(get_responses={"/policy-history/policy-runs": [runs]})
    result = await list_policy_runs_v2(
        cast(AutomoxClient, client),
        org_id=42,
        policy_type="custom",
        limit=10,
        page=1,  # 15 items, limit=10, page=1 → items 10-14, no more pages
    )
    pagination = result["metadata"]["pagination"]
    assert pagination["has_more"] is False
    assert "next_page" not in pagination
    assert "suggested_next_call" not in result["metadata"]


@pytest.mark.asyncio
async def test_list_runs_handles_empty() -> None:
    client = _make_client(get_responses={"/policy-history/policy-runs": [[]]})
    result = await list_policy_runs_v2(cast(AutomoxClient, client), org_id=42)
    assert result["data"]["total_runs"] == 0


# ---------------------------------------------------------------------------
# policy_run_count
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_count_returns_data() -> None:
    client = _make_client(get_responses={"/policy-history/policy-run-count": [{"count": 150}]})
    result = await policy_run_count(cast(AutomoxClient, client), org_id=42)

    assert result["data"]["count"] == 150
    assert result["data"]["org_uuid"] == _ORG_UUID


@pytest.mark.asyncio
async def test_run_count_passes_days() -> None:
    client = _make_client(get_responses={"/policy-history/policy-run-count": [{"count": 5}]})
    await policy_run_count(cast(AutomoxClient, client), org_id=42, days=7)

    params = client.calls[0][2]
    assert params["days"] == 7


# ---------------------------------------------------------------------------
# policy_runs_by_policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runs_by_policy_returns_groups() -> None:
    groups = [
        {"policy_uuid": "pol-001", "policy_name": "Patch", "total_runs": 10},
        {"policy_uuid": "pol-002", "policy_name": "Custom", "total_runs": 5},
    ]
    client = _make_client(get_responses={"/policy-history/policy-runs/grouped-by/policy": [groups]})
    result = await policy_runs_by_policy(cast(AutomoxClient, client), org_id=42)

    assert result["data"]["total_policies"] == 2


# ---------------------------------------------------------------------------
# get_policy_history_detail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_history_detail_returns_policy_with_runs() -> None:
    """Bug #4b from issue #43: the detail tool used to return only
    top-level policy metadata despite the description promising "run
    history and status." It now fetches /policy-runs/{uuid} concurrently
    and merges runs + banner_stats into the response."""
    # policy_success_rate is a PERCENT (0–100), not a fraction — live 2026-06-05
    # returned 0.0 / 60.0 / 100.0 alongside count companions.
    runs_payload = {
        "data": {
            "runs": _POLICY_RUNS,
            "banner_stats": {
                "policy_success_rate": 60.0,
                "total_policies_applied": 57,
                "total_successful_devices": 55,
            },
        },
        "metadata": {"total_run_count": 2},
    }
    client = _make_client(
        get_responses={
            "/policy-history/policies/pol-001": [_POLICY_HISTORY],
            "/policy-history/policy-runs/pol-001": [runs_payload],
        }
    )
    result = await get_policy_history_detail(
        cast(AutomoxClient, client),
        org_id=42,
        policy_uuid="pol-001",
    )

    assert result["data"]["uuid"] == "pol-001"
    assert result["data"]["last_run_time"] == "2026-03-01T01:00:00Z"
    assert result["data"]["total_runs_returned"] == 2
    assert len(result["data"]["recent_runs"]) == 2
    assert result["data"]["recent_runs"][0]["policy_uuid"] == "pol-001"
    assert result["data"]["banner_stats"]["policy_success_rate"] == 60.0
    # The percent-vs-fraction legend is attached so the model reads 60.0 right.
    note = result["metadata"]["field_notes"]["banner_stats.policy_success_rate"]
    assert "Percentage" in note and "NOT a 0–1 fraction" in note


@pytest.mark.asyncio
async def test_history_detail_runs_fetch_failure_does_not_block_detail() -> None:
    """When the runs sub-call fails, the detail still returns; the
    error surfaces in metadata.runs_fetch_error."""
    from automox_mcp.client import AutomoxAPIError

    class FailingRunsClient(StubClient):
        async def get(self, path: str, *, params=None, headers=None):  # type: ignore[override]
            if path.startswith("/policy-history/policy-runs/"):
                raise AutomoxAPIError("runs endpoint down", status_code=500)
            return await super().get(path, params=params, headers=headers)

    client = FailingRunsClient(
        get_responses={"/policy-history/policies/pol-001": [_POLICY_HISTORY]}
    )
    client.org_uuid = _ORG_UUID
    result = await get_policy_history_detail(
        cast(AutomoxClient, client),
        org_id=42,
        policy_uuid="pol-001",
    )
    assert result["data"]["uuid"] == "pol-001"
    assert result["data"]["recent_runs"] == []
    assert result["data"]["total_runs_returned"] == 0
    assert "runs_fetch_error" in result["metadata"]
    assert "runs endpoint down" in result["metadata"]["runs_fetch_error"]


# ---------------------------------------------------------------------------
# get_policy_runs_for_policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runs_for_policy_returns_runs() -> None:
    # /policy-runs/{policyUuid} returns RunsByPolicyResponse shape
    # policy_success_rate is a PERCENT (0–100), live-shaped value.
    runs_response = {
        "data": {
            "runs": _POLICY_RUNS,
            "banner_stats": {
                "policy_success_rate": 95.5,
                "total_policies_applied": 57,
                "total_successful_devices": 55,
            },
        },
        "metadata": {"total_run_count": 2, "last_run_time": "2026-03-01T01:00:00Z"},
    }
    client = _make_client(get_responses={"/policy-history/policy-runs/pol-001": [runs_response]})
    result = await get_policy_runs_for_policy(
        cast(AutomoxClient, client),
        org_id=42,
        policy_uuid="pol-001",
    )

    assert result["data"]["total_runs"] == 2
    assert result["data"]["policy_uuid"] == "pol-001"
    assert result["data"]["banner_stats"]["policy_success_rate"] == 95.5
    assert result["metadata"]["total_run_count"] == 2
    # The percent-vs-fraction legend rides along on the non-summary path.
    note = result["metadata"]["field_notes"]["banner_stats.policy_success_rate"]
    assert "Percentage" in note


@pytest.mark.asyncio
async def test_runs_for_policy_passes_params() -> None:
    empty_response = {
        "data": {"runs": [], "banner_stats": {}},
        "metadata": {"total_run_count": 0},
    }
    client = _make_client(
        get_responses={"/policy-history/policy-runs/pol-001": [empty_response]},
    )
    await get_policy_runs_for_policy(
        cast(AutomoxClient, client),
        org_id=42,
        policy_uuid="pol-001",
        report_days=30,
        sort="desc",
    )

    params = client.calls[0][2]
    assert params["report_days"] == 30
    assert params["sort"] == "desc"


# ---------------------------------------------------------------------------
# get_policy_run_detail_v2
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_detail_returns_results() -> None:
    client = _make_client(
        get_responses={"/policy-history/policies/pol-001/exec-001": [_RUN_DETAIL_RESULTS]}
    )
    result = await get_policy_run_detail_v2(
        cast(AutomoxClient, client),
        org_id=42,
        policy_uuid="pol-001",
        exec_token="exec-001",
    )

    assert result["data"]["total_results"] == 2
    assert result["data"]["exec_token"] == "exec-001"
    # The exit_code/result_status legend rides along so the model never has
    # to guess what a negative NTSTATUS-style code means.
    notes = result["metadata"]["field_notes"]
    assert "NTSTATUS" in notes["exit_code"]
    assert "result_status" in notes


@pytest.mark.asyncio
async def test_run_detail_passes_filters() -> None:
    client = _make_client(
        get_responses={"/policy-history/policies/pol-001/exec-001": [[]]},
    )
    await get_policy_run_detail_v2(
        cast(AutomoxClient, client),
        org_id=42,
        policy_uuid="pol-001",
        exec_token="exec-001",
        result_status="failure",
        device_name="host-1",
        limit=5,
    )

    params = client.calls[0][2]
    assert params["result_status"] == "failure"
    assert params["device_name"] == "host-1"
    assert params["limit"] == 5
    # The policy-report-api requires the org UUID as a query param;
    # without it the API rejects the request with `org=null`.
    assert params["org"] == _ORG_UUID


# ---------------------------------------------------------------------------
# get_policy_runs_for_policy: summary_only (issue #91 category J)
# ---------------------------------------------------------------------------


_RUNS_WITH_STATS = {
    "data": {
        "runs": _POLICY_RUNS,
        "banner_stats": {"success": 12, "failed": 1},
    },
    "metadata": {},
}


@pytest.mark.asyncio
async def test_runs_for_policy_full_includes_stats_and_banner() -> None:
    client = _make_client(get_responses={"/policy-history/policy-runs": [_RUNS_WITH_STATS]})
    result = await get_policy_runs_for_policy(
        cast(AutomoxClient, client), org_id=42, policy_uuid="pol-001"
    )
    data = result["data"]
    assert "banner_stats" in data
    assert data["banner_stats"] == {"success": 12, "failed": 1}
    # full mode keeps the rich per-run fields
    assert data["runs"][0]["device_outcomes"]["success"] == 9
    assert data["runs"][0]["policy_type"] == "patch"


@pytest.mark.asyncio
async def test_runs_for_policy_summary_only_projects_and_drops_banner() -> None:
    client = _make_client(get_responses={"/policy-history/policy-runs": [_RUNS_WITH_STATS]})
    result = await get_policy_runs_for_policy(
        cast(AutomoxClient, client),
        org_id=42,
        policy_uuid="pol-001",
        summary_only=True,
    )
    data = result["data"]
    assert "banner_stats" not in data
    # banner_stats is dropped on the lean path, so its legend must not appear.
    assert "field_notes" not in result["metadata"]
    assert data["total_runs"] == 2
    first = data["runs"][0]
    assert set(first.keys()) <= {"policy_uuid", "run_time", "execution_token", "run_count"}
    assert first["policy_uuid"] == "pol-001"
    assert first["execution_token"] == "exec-001"
    # second run had no run_count upstream -> omitted, not None
    assert "run_count" not in data["runs"][1]


# ---------------------------------------------------------------------------
# list_policy_execution_counts (issue #91 category I)
# ---------------------------------------------------------------------------


_EXEC_COUNTS = {
    "data": [
        {
            "org_uuid": _ORG_UUID,
            "policy_id": 101,
            "policy_name": "Patch Tuesday",
            "policy_uuid": "pol-001",
            "exec_time": "2026-03-01T00:00:00Z",
            "run_count": 100,
        },
        {
            "org_uuid": _ORG_UUID,
            "policy_id": 102,
            "policy_name": "Weekly Worklet",
            "policy_uuid": "pol-002",
            "exec_time": "2026-03-02T00:00:00Z",
            "run_count": 12,
        },
    ]
}


@pytest.mark.asyncio
async def test_execution_counts_projects_rows_and_forwards_window() -> None:
    client = _make_client(get_responses={"/policy-history/policies": [_EXEC_COUNTS]})
    result = await list_policy_execution_counts(
        cast(AutomoxClient, client),
        org_id=42,
        start_time="2026-01-01T00:00:00Z",
        end_time="2026-04-01T00:00:00Z",
    )
    data = result["data"]
    assert data["total_policies"] == 2
    assert data["policies"][0]["policy_name"] == "Patch Tuesday"
    assert data["policies"][0]["run_count"] == 100

    _, path, params = client.calls[0]
    assert path == "/policy-history/policies"
    assert params["org"] == _ORG_UUID
    assert params["start_time"] == "2026-01-01T00:00:00Z"
    assert params["end_time"] == "2026-04-01T00:00:00Z"


@pytest.mark.asyncio
async def test_execution_counts_window_optional() -> None:
    client = _make_client(get_responses={"/policy-history/policies": [{"data": []}]})
    result = await list_policy_execution_counts(cast(AutomoxClient, client), org_id=42)
    assert result["data"]["total_policies"] == 0
    _, _path, params = client.calls[0]
    assert "start_time" not in params
    assert "end_time" not in params
    assert params["org"] == _ORG_UUID
