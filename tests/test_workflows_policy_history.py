"""Tests for policy history v2 workflows."""

from typing import Any, cast

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.policy_history import (
    get_policy_history_detail,
    get_policy_run_detail_v2,
    get_policy_runs_for_policy,
    list_policy_runs_v2,
    policy_run_count,
    policy_runs_by_policy,
)

_ORG_UUID = "11111111-2222-3333-4444-555555555555"

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
    assert result["data"]["runs"][0]["success"] == 9


@pytest.mark.asyncio
async def test_list_runs_passes_filters() -> None:
    client = _make_client(get_responses={"/policy-history/policy-runs": [[]]})
    await list_policy_runs_v2(
        cast(AutomoxClient, client),
        org_id=42,
        start_time="2026-01-01",
        policy_type="patch",
        result_status="failure",
        limit=10,
    )

    _, path, params = client.calls[0]
    assert params["start_time"] == "2026-01-01"
    assert params["policy_type"] == "patch"
    assert params["result_status"] == "failure"
    assert params["limit"] == 10


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
async def test_history_detail_returns_policy() -> None:
    client = _make_client(get_responses={"/policy-history/policies/pol-001": [_POLICY_HISTORY]})
    result = await get_policy_history_detail(
        cast(AutomoxClient, client),
        org_id=42,
        policy_uuid="pol-001",
    )

    assert result["data"]["uuid"] == "pol-001"
    assert result["data"]["last_run_time"] == "2026-03-01T01:00:00Z"


# ---------------------------------------------------------------------------
# get_policy_runs_for_policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runs_for_policy_returns_runs() -> None:
    # /policy-runs/{policyUuid} returns RunsByPolicyResponse shape
    runs_response = {
        "data": {
            "runs": _POLICY_RUNS,
            "banner_stats": {
                "policy_success_rate": 0.9,
                "total_policies_applied": 2,
                "total_successful_devices": 12,
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
    assert result["data"]["banner_stats"]["policy_success_rate"] == 0.9
    assert result["metadata"]["total_run_count"] == 2


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
    assert "org" not in params  # org comes from JWT, not query params
