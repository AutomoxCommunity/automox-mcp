"""Policy History v2 tools for Automox MCP."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import ValidationError

from ..client import AutomoxAPIError, AutomoxClient
from ..utils.organization import resolve_org_uuid
from ..utils.tooling import (
    RateLimitError,
    as_tool_response,
    enforce_rate_limit,
    format_error,
    format_validation_error,
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

    async def _resolve_uuid() -> str:
        return await resolve_org_uuid(client, org_id=client.org_id)

    async def _call_workflow(
        func: Callable[..., Awaitable[dict[str, Any]]],
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            await enforce_rate_limit()
            kwargs.setdefault("org_id", client.org_id)
            if kwargs.get("org_id") is None:
                raise ToolError("org_id required - set AUTOMOX_ORG_ID or pass org_id explicitly.")
            result: dict[str, Any] = await func(client, **kwargs)
        except (ValidationError, ValueError) as exc:
            raise ToolError(format_validation_error(exc)) from exc
        except RateLimitError as exc:
            raise ToolError(str(exc)) from exc
        except AutomoxAPIError as exc:
            raise ToolError(format_error(exc)) from exc
        except ToolError:
            raise
        except Exception as exc:
            logger.exception("Unexpected error in tool call")
            raise ToolError("An internal error occurred. Check server logs for details.") from exc
        return as_tool_response(result)

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
        result = await _call_workflow(
            _list_policy_runs_v2,
            {
                "start_time": start_time,
                "end_time": end_time,
                "policy_name": policy_name,
                "policy_uuid": policy_uuid,
                "policy_type": policy_type,
                "result_status": result_status,
                "sort": sort,
                "page": page,
                "limit": limit,
            },
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
        result = await _call_workflow(
            _policy_run_count,
            {"days": days},
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
        result = await _call_workflow(
            _policy_runs_by_policy,
            {},
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
        result = await _call_workflow(
            _get_policy_history_detail,
            {"policy_uuid": policy_uuid},
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
        result = await _call_workflow(
            _get_policy_runs_for_policy,
            {
                "policy_uuid": policy_uuid,
                "report_days": report_days,
                "sort": sort,
            },
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
        result = await _call_workflow(
            _get_policy_run_detail_v2,
            {
                "policy_uuid": policy_uuid,
                "exec_token": exec_token,
                "sort": sort,
                "result_status": result_status,
                "device_name": device_name,
                "page": page,
                "limit": limit,
            },
        )
        return maybe_format_markdown(result, output_format)


__all__ = ["register"]
