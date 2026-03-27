"""Policy History v2 workflows for Automox MCP."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from ..client import AutomoxClient
from ..utils import resolve_org_uuid


def _summarize_run(run: Mapping[str, Any]) -> dict[str, Any]:
    """Extract key fields from a policy run record."""
    entry: dict[str, Any] = {}
    for key in (
        "uuid",
        "policy_uuid",
        "policy_name",
        "policy_type",
        "status",
        "result_status",
        "started_at",
        "completed_at",
        "device_count",
        "success_count",
        "failure_count",
    ):
        val = run.get(key)
        if val is not None:
            entry[key] = val
    return entry


def _summarize_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    """Extract key fields from a policy history record."""
    entry: dict[str, Any] = {}
    for key in (
        "uuid",
        "name",
        "policy_type",
        "policy_type_name",
        "status",
        "last_run_at",
        "run_count",
        "created_at",
    ):
        val = policy.get(key)
        if val is not None:
            entry[key] = val
    return entry


def _extract_list(response: Any) -> list[Mapping[str, Any]]:
    """Normalize API response into a list of mappings."""
    if isinstance(response, Sequence) and not isinstance(response, (str, bytes)):
        return [item for item in response if isinstance(item, Mapping)]
    if isinstance(response, Mapping):
        data = response.get("data")
        if isinstance(data, Sequence) and not isinstance(data, (str, bytes)):
            return [item for item in data if isinstance(item, Mapping)]
        return [response]
    return []


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

    # Policy History v2 requires org UUID as a query parameter
    params: dict[str, Any] = {"org": resolved_uuid}
    if start_time:
        params["startTime"] = start_time
    if end_time:
        params["endTime"] = end_time
    if policy_name:
        params["policyName"] = policy_name
    if policy_uuid:
        params["policyUuid"] = policy_uuid
    if policy_type:
        params["policyType"] = policy_type
    if result_status:
        params["resultStatus"] = result_status
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
        params["reportDays"] = report_days
    if sort:
        params["sort"] = sort

    response = await client.get(
        f"/policy-history/policies/{policy_uuid}/runs",
        params=params,
    )

    runs = _extract_list(response)
    summaries = [_summarize_run(r) for r in runs]

    return {
        "data": {
            "org_uuid": resolved_uuid,
            "policy_uuid": policy_uuid,
            "total_runs": len(summaries),
            "runs": summaries,
        },
        "metadata": {"deprecated_endpoint": False},
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

    params: dict[str, Any] = {"org": resolved_uuid}
    if sort:
        params["sort"] = sort
    if result_status:
        params["resultStatus"] = result_status
    if device_name:
        params["deviceName"] = device_name
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
