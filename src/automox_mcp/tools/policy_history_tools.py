"""Policy History v2 tools for Automox MCP."""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP

from ..client import AutomoxClient
from ..schemas import (
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
    list_policy_runs_v2 as _list_policy_runs_v2,
)
from ..workflows.policy_history import (
    policy_run_count as _policy_run_count,
)
from ..workflows.policy_history import (
    policy_runs_by_policy as _policy_runs_by_policy,
)

logger = logging.getLogger(__name__)


def register(server: FastMCP, *, read_only: bool = False, client: AutomoxClient) -> None:
    """Register policy history v2 tools."""

    @server.tool(
        name="policy_runs_v2",
        description=(
            "List policy runs with time-range filtering, policy name/type filters, "
            "and result status filtering. Uses the Policy History v2 API for richer "
            "data than the standard policy execution timeline."
        ),
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
        description=("Get policy history details by UUID, including run history and status."),
    )
    async def policy_history_detail(
        policy_uuid: str,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"policy_uuid": policy_uuid}
        result = await call_tool_workflow(
            client, _get_policy_history_detail, kwargs, params_model=PolicyHistoryDetailParams
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="policy_runs_for_policy",
        description=(
            "Get execution runs for a specific policy by UUID. "
            "Optionally filter by number of days and sort order."
        ),
    )
    async def policy_runs_for_policy(
        policy_uuid: str,
        report_days: int | None = None,
        sort: str | None = None,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "policy_uuid": policy_uuid,
            "report_days": report_days,
            "sort": sort,
        }
        result = await call_tool_workflow(
            client, _get_policy_runs_for_policy, kwargs, params_model=PolicyRunsForPolicyParams
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="policy_run_detail_v2",
        description=(
            "Get detailed per-device results for a specific policy run. "
            "Uses UUID-based queries and supports device name filtering."
        ),
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
