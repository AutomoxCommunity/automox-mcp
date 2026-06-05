"""Policy History v2 tools for Automox MCP."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from ..client import AutomoxClient
from ..schemas import (
    PolicyExecutionCountsParams,
    PolicyHistoryDetailParams,
    PolicyRunCountParams,
    PolicyRunDetailV2Params,
    PolicyRunsByPolicyParams,
    PolicyRunsForPolicyParams,
    PolicyRunsV2Params,
)
from ..utils.tooling import (
    call_tool_workflow,
    maybe_format_markdown,
)
from ..workflows.policy_history import (
    get_policy_history_detail as _get_policy_history_detail,
)
from ..workflows.policy_history import (
    get_policy_run_detail_v2 as _get_policy_run_detail_v2,
)
from ..workflows.policy_history import (
    get_policy_runs_for_policy as _get_policy_runs_for_policy,
)
from ..workflows.policy_history import (
    list_policy_execution_counts as _list_policy_execution_counts,
)
from ..workflows.policy_history import (
    list_policy_runs_v2 as _list_policy_runs_v2,
)
from ..workflows.policy_history import (
    policy_run_count as _policy_run_count,
)
from ..workflows.policy_history import (
    policy_runs_by_policy as _policy_runs_by_policy,
)


def register(server: FastMCP, *, read_only: bool = False, client: AutomoxClient) -> None:
    """Register policy history v2 tools."""

    @server.tool(
        name="policy_runs_v2",
        description=(
            "List policy runs with time-range filtering, policy name/type filters, "
            "and result status filtering. Uses the Policy History v2 API for richer "
            "data than the standard policy execution timeline. Each run's "
            "`device_outcomes` (pending/success/failed/not_included/"
            "remediation_not_applicable/blocked) are DEVICE COUNTS per outcome "
            "for that run, not run statuses. `result_status` filters with "
            "any-device-with-this-outcome semantics: a run matches when AT LEAST "
            "ONE device had that outcome — it does NOT mean every device did "
            "(live-verified 2026-06-05: result_status='failed' returns runs with "
            "1 failed device alongside 200+ not-failed). The same run can match "
            "multiple result_status values."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def policy_runs_v2(
        start_time: str | None = None,
        end_time: str | None = None,
        policy_name: str | None = None,
        policy_uuid: str | None = None,
        policy_type: str | None = None,
        result_status: str | None = None,
        sort: str | None = None,
        page: int | None = None,
        limit: int | None = None,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "start_time": start_time,
            "end_time": end_time,
            "policy_name": policy_name,
            "policy_uuid": policy_uuid,
            "policy_type": policy_type,
            "result_status": result_status,
            "sort": sort,
            "page": page,
            "limit": limit,
        }
        result = await call_tool_workflow(
            client, _list_policy_runs_v2, kwargs, params_model=PolicyRunsV2Params
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="policy_run_count",
        description=(
            "Get aggregate policy execution counts. "
            "Optionally filter by number of days to look back."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def policy_run_count(
        days: int | None = None,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"days": days}
        result = await call_tool_workflow(
            client, _policy_run_count, kwargs, params_model=PolicyRunCountParams
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="policy_runs_by_policy",
        description=(
            "Get policy runs grouped by policy for cross-policy comparison. "
            "Shows which policies have been running and their aggregate results."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def policy_runs_by_policy(
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        result = await call_tool_workflow(
            client, _policy_runs_by_policy, kwargs, params_model=PolicyRunsByPolicyParams
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="policy_history_detail",
        description=(
            "Get policy history details by UUID, including run history and status. "
            "Each run's `device_outcomes` are device counts per outcome, not run statuses."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def policy_history_detail(
        policy_uuid: str,
        recent_runs_limit: int | None = 25,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "policy_uuid": policy_uuid,
            "recent_runs_limit": recent_runs_limit,
        }
        result = await call_tool_workflow(
            client, _get_policy_history_detail, kwargs, params_model=PolicyHistoryDetailParams
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="policy_runs_for_policy",
        description=(
            "Get execution runs for a specific policy by UUID. "
            "Optionally filter by number of days and sort order. Each run's "
            "`device_outcomes` are device counts per outcome, not run statuses."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def policy_runs_for_policy(
        policy_uuid: str,
        report_days: int | None = None,
        sort: str | None = None,
        summary_only: bool = False,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "policy_uuid": policy_uuid,
            "report_days": report_days,
            "sort": sort,
            "summary_only": summary_only,
        }
        result = await call_tool_workflow(
            client, _get_policy_runs_for_policy, kwargs, params_model=PolicyRunsForPolicyParams
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="policy_execution_counts",
        description=(
            "List fleet-wide policy execution counts over a time window: one row per "
            "policy with its run count, in a single round-trip. Answers 'which policies "
            "ran most last quarter?' without per-policy calls or client-side aggregation. "
            "Distinct from policy_run_count (single aggregate) and policy_runs_for_policy "
            "(per-run records for one policy)."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def policy_execution_counts(
        start_time: str | None = None,
        end_time: str | None = None,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "start_time": start_time,
            "end_time": end_time,
        }
        result = await call_tool_workflow(
            client,
            _list_policy_execution_counts,
            kwargs,
            params_model=PolicyExecutionCountsParams,
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="policy_run_detail_v2",
        description=(
            "Get detailed per-device results for a specific policy run. "
            "Uses UUID-based queries and supports device name filtering. "
            "`exit_code` is the raw process exit code from the policy script "
            "(0 = success; negative values on Windows are NTSTATUS codes as "
            "signed 32-bit ints); `result_status` is the lowercase per-device "
            "outcome (e.g. success, failed)."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def policy_run_detail_v2(
        policy_uuid: str,
        exec_token: str,
        sort: str | None = None,
        result_status: str | None = None,
        device_name: str | None = None,
        page: int | None = None,
        limit: int | None = None,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "policy_uuid": policy_uuid,
            "exec_token": exec_token,
            "sort": sort,
            "result_status": result_status,
            "device_name": device_name,
            "page": page,
            "limit": limit,
        }
        result = await call_tool_workflow(
            client, _get_policy_run_detail_v2, kwargs, params_model=PolicyRunDetailV2Params
        )
        return maybe_format_markdown(result, output_format)


__all__ = ["register"]
