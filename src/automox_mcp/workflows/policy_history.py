"""Policy History v2 workflows for Automox MCP."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from ..client import AutomoxClient
from ..utils import resolve_org_uuid
from ..utils.response import extract_list as _extract_list


def _summarize_run(run: Mapping[str, Any]) -> dict[str, Any]:
    """Extract key fields from a policy run record.

    The policy-report-api returns snake_case JSON via @JsonNaming(SnakeCaseStrategy).
    Fields: policy_uuid, policy_id, org_uuid, policy_name, policy_type,
    policy_deleted_at, pending, success, remediation_not_applicable, failed,
    not_included, run_time, execution_token, run_count, blocked (v2 only).
    """
    entry: dict[str, Any] = {}
    for key in (
        "policy_uuid",
        "policy_id",
        "org_uuid",
        "policy_name",
        "policy_type",
        "policy_deleted_at",
        "pending",
        "success",
        "remediation_not_applicable",
        "failed",
        "not_included",
        "run_time",
        "execution_token",
        "run_count",
        "blocked",
    ):
        val = run.get(key)
        if val is not None:
            entry[key] = val
    return entry


def _summarize_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    """Extract key fields from a policy info record.

    The policy-report-api PolicyInfoResource returns snake_case JSON:
    uuid, id, org_uuid, name, type, deleted_at, updated_at, last_run_time.
    """
    entry: dict[str, Any] = {}
    for key in (
        "uuid",
        "id",
        "org_uuid",
        "name",
        "type",
        "deleted_at",
        "updated_at",
        "last_run_time",
    ):
        val = policy.get(key)
        if val is not None:
            entry[key] = val
    return entry


async def list_policy_runs_v2(
    client: AutomoxClient,
    *,
    org_id: int,
    org_uuid: str | UUID | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    policy_name: str | None = None,
    policy_uuid: str | None = None,
    policy_type: str | None = None,
    result_status: str | None = None,
    sort: str | None = None,
    page: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """List policy runs with optional filtering and time-range queries."""
    resolved_uuid = await resolve_org_uuid(
        client,
        explicit_uuid=org_uuid,
        org_id=org_id,
    )

    # Policy History v2 requires org UUID as a query parameter.
    # The policy-report-api uses snake_case query parameter names.
    params: dict[str, Any] = {"org": resolved_uuid}
    if start_time:
        params["start_time"] = start_time
    if end_time:
        params["end_time"] = end_time
    if policy_name:
        params["policy_name"] = policy_name
    if policy_uuid:
        params["policy_uuid"] = policy_uuid
    if policy_type:
        params["policy_type"] = policy_type
    if result_status:
        params["result_status"] = result_status
    if sort:
        params["sort"] = sort
    if page is not None:
        params["page"] = page
    if limit is not None:
        params["limit"] = limit

    response = await client.get(
        "/policy-history/policy-runs",
        params=params,
    )

    runs = _extract_list(response)
    summaries = [_summarize_run(r) for r in runs]

    return {
        "data": {
            "org_uuid": resolved_uuid,
            "total_runs": len(summaries),
            "runs": summaries,
        },
        "metadata": {"deprecated_endpoint": False},
    }


async def policy_run_count(
    client: AutomoxClient,
    *,
    org_id: int,
    org_uuid: str | UUID | None = None,
    days: int | None = None,
) -> dict[str, Any]:
    """Get aggregate policy run counts."""
    resolved_uuid = await resolve_org_uuid(
        client,
        explicit_uuid=org_uuid,
        org_id=org_id,
    )

    params: dict[str, Any] = {"org": resolved_uuid}
    if days is not None:
        params["days"] = days

    response = await client.get(
        "/policy-history/policy-run-count",
        params=params,
    )

    if isinstance(response, Mapping):
        data = dict(response)
    else:
        data = {"count": response}
    data["org_uuid"] = resolved_uuid

    return {
        "data": data,
        "metadata": {"deprecated_endpoint": False},
    }


async def policy_runs_by_policy(
    client: AutomoxClient,
    *,
    org_id: int,
    org_uuid: str | UUID | None = None,
) -> dict[str, Any]:
    """Get policy runs grouped by policy for cross-policy comparison."""
    resolved_uuid = await resolve_org_uuid(
        client,
        explicit_uuid=org_uuid,
        org_id=org_id,
    )

    response = await client.get(
        "/policy-history/policy-runs/grouped-by/policy",
        params={"org": resolved_uuid},
    )

    groups = _extract_list(response)

    return {
        "data": {
            "org_uuid": resolved_uuid,
            "total_policies": len(groups),
            "policy_groups": groups,
        },
        "metadata": {"deprecated_endpoint": False},
    }


async def get_policy_history_detail(
    client: AutomoxClient,
    *,
    org_id: int,
    policy_uuid: str,
    org_uuid: str | UUID | None = None,
) -> dict[str, Any]:
    """Get policy history details by UUID."""
    resolved_uuid = await resolve_org_uuid(
        client,
        explicit_uuid=org_uuid,
        org_id=org_id,
    )

    response = await client.get(
        f"/policy-history/policies/{policy_uuid}",
        params={"org": resolved_uuid},
    )

    if isinstance(response, Mapping):
        detail = _summarize_policy(response)
    else:
        detail = {}

    return {
        "data": detail,
        "metadata": {"deprecated_endpoint": False},
    }


async def get_policy_runs_for_policy(
    client: AutomoxClient,
    *,
    org_id: int,
    policy_uuid: str,
    org_uuid: str | UUID | None = None,
    report_days: int | None = None,
    sort: str | None = None,
) -> dict[str, Any]:
    """Get execution runs for a specific policy by UUID."""
    resolved_uuid = await resolve_org_uuid(
        client,
        explicit_uuid=org_uuid,
        org_id=org_id,
    )

    params: dict[str, Any] = {"org": resolved_uuid}
    if report_days is not None:
        params["report_days"] = report_days
    if sort:
        params["sort"] = sort

    # The correct endpoint for runs-with-stats is /policy-runs/{policyUuid}
    # (not /policies/{policyUuid}/runs which returns only execution tokens).
    # Response shape: { data: { runs: [...], banner_stats: {...} }, metadata: {...} }
    response = await client.get(
        f"/policy-history/policy-runs/{policy_uuid}",
        params=params,
    )

    # Extract runs from the nested response structure
    if isinstance(response, Mapping) and "data" in response:
        data_block = response["data"]
        raw_runs = data_block.get("runs", []) if isinstance(data_block, Mapping) else []
        banner_stats = data_block.get("banner_stats", {}) if isinstance(data_block, Mapping) else {}
        metadata = response.get("metadata", {})
    else:
        raw_runs = _extract_list(response)
        banner_stats = {}
        metadata = {}

    summaries = [_summarize_run(r) for r in raw_runs]

    return {
        "data": {
            "org_uuid": resolved_uuid,
            "policy_uuid": policy_uuid,
            "total_runs": len(summaries),
            "runs": summaries,
            "banner_stats": banner_stats,
        },
        "metadata": metadata,
    }


async def get_policy_run_detail_v2(
    client: AutomoxClient,
    *,
    org_id: int,
    policy_uuid: str,
    exec_token: str,
    org_uuid: str | UUID | None = None,
    sort: str | None = None,
    result_status: str | None = None,
    device_name: str | None = None,
    page: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Get detailed results for a specific policy run by UUID and exec token."""
    resolved_uuid = await resolve_org_uuid(
        client,
        explicit_uuid=org_uuid,
        org_id=org_id,
    )

    # The device details endpoint extracts org from JWT, not query params.
    # Filter params use snake_case names per the policy-report-api.
    params: dict[str, Any] = {}
    if sort:
        params["sort"] = sort
    if result_status:
        params["result_status"] = result_status
    if device_name:
        params["device_name"] = device_name
    if page is not None:
        params["page"] = page
    if limit is not None:
        params["limit"] = limit

    response = await client.get(
        f"/policy-history/policies/{policy_uuid}/{exec_token}",
        params=params,
    )

    results = _extract_list(response)

    return {
        "data": {
            "org_uuid": resolved_uuid,
            "policy_uuid": policy_uuid,
            "exec_token": exec_token,
            "total_results": len(results),
            "results": results,
        },
        "metadata": {"deprecated_endpoint": False},
    }
