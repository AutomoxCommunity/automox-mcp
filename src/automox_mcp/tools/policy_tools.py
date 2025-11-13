"""Policy-related tools for Automox MCP."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, ValidationError

from .. import workflows
from ..client import AutomoxAPIError, AutomoxClient
from ..schemas import (
    ExecutePolicyParams,
    OrgIdContextMixin,
    OrgIdRequiredMixin,
    PatchApprovalDecisionParams,
    PatchApprovalSummaryParams,
    PolicyChangeRequestParams,
    PolicyDetailParams,
    PolicyExecutionTimelineParams,
    PolicyHealthSummaryParams,
    PolicySummaryParams,
    RunDetailParams,
)
from ..utils import resolve_org_uuid
from ..utils.tooling import (
    RateLimitError,
    as_tool_response,
    enforce_rate_limit,
    format_error,
)


def register(server: FastMCP) -> None:
    """Register policy-related tools."""

    async def _call(
        func: Callable[..., Awaitable[dict[str, Any]]],
        params_model: type[BaseModel],
        raw_params: dict[str, Any],
        api: str | None = None,
        org_uuid_field: str | None = None,
        allow_account_uuid: bool = False,
    ) -> dict[str, Any]:
        try:
            await enforce_rate_limit(api)
            client = AutomoxClient(default_api=api)
            client_org_id = getattr(client, "org_id", None)
            async with client as session:
                params = dict(raw_params)
                if org_uuid_field is not None:
                    resolved_uuid = await resolve_org_uuid(
                        session,
                        explicit_uuid=params.get(org_uuid_field),
                        org_id=params.get("org_id") or client_org_id,
                        allow_account_uuid=allow_account_uuid,
                    )
                    params[org_uuid_field] = resolved_uuid
                if issubclass(params_model, (OrgIdContextMixin, OrgIdRequiredMixin)):
                    params.setdefault("org_id", client_org_id)
                    if params.get("org_id") is None:
                        raise ToolError(
                            "org_id required - set AUTOMOX_ORG_ID or pass org_id explicitly."
                        )
                model = params_model(**params)
                payload = model.model_dump(mode="python", exclude_none=True)
                if isinstance(model, (OrgIdContextMixin, OrgIdRequiredMixin)):
                    payload["org_id"] = model.org_id
                result: dict[str, Any] = await func(session, **payload)
        except (ValidationError, ValueError) as exc:
            raise ToolError(str(exc)) from exc
        except RateLimitError as exc:
            raise ToolError(str(exc)) from exc
        except AutomoxAPIError as exc:
            raise ToolError(format_error(exc)) from exc
        return as_tool_response(result)

    @server.tool(
        name="policy_health_overview", description="Summarize recent Automox policy activity."
    )
    async def policy_health_overview(
        org_uuid: str | None = None,
        window_days: int | None = 7,
        top_failures: int | None = 5,
        max_runs: int | None = 200,
    ) -> dict[str, Any]:
        params = {
            "org_uuid": org_uuid,
            "window_days": window_days,
            "top_failures": top_failures,
            "max_runs": max_runs,
        }
        return await _call(
            workflows.summarize_policy_activity,
            PolicyHealthSummaryParams,
            params,
            api="policyreport",
            org_uuid_field="org_uuid",
            allow_account_uuid=True,
        )

    @server.tool(
        name="policy_execution_timeline", description="Review recent executions for a policy."
    )
    async def policy_execution_timeline(
        policy_uuid: str,
        org_uuid: str | None = None,
        report_days: int | None = 7,
        limit: int | None = 50,
    ) -> dict[str, Any]:
        params = {
            "org_uuid": org_uuid,
            "policy_uuid": policy_uuid,
            "report_days": report_days,
            "limit": limit,
        }
        return await _call(
            workflows.summarize_policy_execution_history,
            PolicyExecutionTimelineParams,
            params,
            api="policyreport",
            org_uuid_field="org_uuid",
            allow_account_uuid=True,
        )

    @server.tool(
        name="policy_run_results",
        description="Retrieve per-device results and output for a specific policy execution token.",
    )
    async def policy_run_results(
        policy_uuid: str,
        exec_token: str,
        org_uuid: str | None = None,
        sort: str | None = None,
        result_status: str | None = None,
        device_name: str | None = None,
        page: int | None = None,
        limit: int | None = None,
        max_output_length: int | None = None,
    ) -> dict[str, Any]:
        params = {
            "policy_uuid": policy_uuid,
            "exec_token": exec_token,
            "org_uuid": org_uuid,
            "sort": sort,
            "result_status": result_status,
            "device_name": device_name,
            "page": page,
            "limit": limit,
            "max_output_length": max_output_length,
        }
        return await _call(
            workflows.describe_policy_run_result,
            RunDetailParams,
            params,
            api="policyreport",
            org_uuid_field="org_uuid",
            allow_account_uuid=True,
        )

    @server.tool(
        name="policy_catalog", description="List Automox policies with type and status summaries."
    )
    async def policy_catalog(
        limit: int | None = 20,
        page: int | None = 0,
        include_inactive: bool | None = False,
    ) -> dict[str, Any]:
        params = {
            "limit": limit,
            "page": page,
            "include_inactive": include_inactive,
        }
        return await _call(
            workflows.summarize_policies,
            PolicySummaryParams,
            params,
            api="console",
        )

    @server.tool(
        name="policy_detail", description="Retrieve configuration and recent history for a policy."
    )
    async def policy_detail(
        policy_id: int,
        include_recent_runs: int | None = 5,
    ) -> dict[str, Any]:
        params = {
            "policy_id": policy_id,
            "include_recent_runs": include_recent_runs,
        }
        return await _call(
            workflows.describe_policy,
            PolicyDetailParams,
            params,
            api="console",
        )

    @server.tool(
        name="patch_approvals_summary",
        description="Summarize pending patch approvals and their severity.",
    )
    async def patch_approvals_summary(
        status: str | None = None,
        limit: int | None = 25,
    ) -> dict[str, Any]:
        params = {
            "status": status,
            "limit": limit,
        }
        return await _call(
            workflows.summarize_patch_approvals,
            PatchApprovalSummaryParams,
            params,
            api="console",
        )

    @server.tool(
        name="decide_patch_approval",
        description="Approve or reject an Automox patch approval request.",
        annotations={"destructiveHint": True},
    )
    async def decide_patch_approval(
        approval_id: int,
        decision: str,
        notes: str | None = None,
    ) -> dict[str, Any]:
        params = {
            "approval_id": approval_id,
            "decision": decision,
            "notes": notes,
        }
        return await _call(
            workflows.resolve_patch_approval,
            PatchApprovalDecisionParams,
            params,
            api="console",
        )

    @server.tool(
        name="apply_policy_changes",
        description="Create or update Automox policies with automatic format correction.",
        annotations={"destructiveHint": True},
    )
    async def apply_policy_changes_tool(
        operations: list[dict[str, Any]],
        preview: bool | None = False,
    ) -> dict[str, Any]:
        normalized_operations = workflows.normalize_policy_operations_input(operations)
        params = {
            "operations": normalized_operations,
            "preview": preview,
        }
        return await _call(
            workflows.apply_policy_changes,
            PolicyChangeRequestParams,
            params,
            api="console",
        )

    @server.tool(
        name="execute_policy_now",
        description=(
            "Execute an Automox policy immediately for remediation "
            "(all devices or specific device)."
        ),
        annotations={"destructiveHint": True},
    )
    async def execute_policy_now(
        policy_id: int,
        action: str,
        device_id: int | None = None,
    ) -> dict[str, Any]:
        params = {
            "policy_id": policy_id,
            "action": action,
            "device_id": device_id,
        }
        return await _call(
            workflows.execute_policy,
            ExecutePolicyParams,
            params,
            api="console",
        )


__all__ = ["register"]
