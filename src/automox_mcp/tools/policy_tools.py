"""Policy-related tools for Automox MCP."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, ValidationError

from .. import workflows
from ..client import AutomoxAPIError, AutomoxClient
from ..schemas import (
    ClonePolicyParams,
    DeletePolicyToolParams,
    ExecutePolicyParams,
    GetPolicyStatsParams,
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
    check_idempotency,
    enforce_rate_limit,
    format_error,
    maybe_format_markdown,
    store_idempotency,
)

logger = logging.getLogger(__name__)


def register(server: FastMCP, *, read_only: bool = False, client: AutomoxClient) -> None:
    """Register policy-related tools."""

    async def _call(
        func: Callable[..., Awaitable[dict[str, Any]]],
        params_model: type[BaseModel],
        raw_params: dict[str, Any],
        org_uuid_field: str | None = None,
        allow_account_uuid: bool = False,
    ) -> dict[str, Any]:
        try:
            await enforce_rate_limit()
            client_org_id = client.org_id
            params = dict(raw_params)
            if org_uuid_field is not None:
                raw_org_id = params.get("org_id")
                resolved_uuid = await resolve_org_uuid(
                    client,
                    explicit_uuid=params.get(org_uuid_field),
                    org_id=raw_org_id if raw_org_id is not None else client_org_id,
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
            result: dict[str, Any] = await func(client, **payload)
        except (ValidationError, ValueError) as exc:
            raise ToolError(str(exc)) from exc
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
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        params = {
            "limit": limit,
            "page": page,
            "include_inactive": include_inactive,
        }
        result = await _call(
            workflows.summarize_policies,
            PolicySummaryParams,
            params,
        )

        return maybe_format_markdown(result, output_format)

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
        )

    @server.tool(
        name="policy_compliance_stats",
        description=(
            "Retrieve per-policy compliance statistics showing compliant vs "
            "non-compliant device counts and compliance rates for the organization."
        ),
    )
    async def policy_compliance_stats() -> dict[str, Any]:
        return await _call(
            workflows.get_policy_compliance_stats,
            GetPolicyStatsParams,
            {},
        )

    @server.tool(
        name="patch_approvals_summary",
        description="Summarize pending patch approvals and their severity.",
    )
    async def patch_approvals_summary(
        status: str | None = None,
        limit: int | None = 25,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        params = {
            "status": status,
            "limit": limit,
        }
        result = await _call(
            workflows.summarize_patch_approvals,
            PatchApprovalSummaryParams,
            params,
        )

        return maybe_format_markdown(result, output_format)

    if not read_only:

        @server.tool(
            name="decide_patch_approval",
            description="Approve or reject an Automox patch approval request.",
            annotations={"destructiveHint": True},
        )
        async def decide_patch_approval(
            approval_id: int,
            decision: str,
            notes: str | None = None,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "decide_patch_approval")
            if cached is not None:
                return cached

            params = {
                "approval_id": approval_id,
                "decision": decision,
                "notes": notes,
            }
            result = await _call(
                workflows.resolve_patch_approval,
                PatchApprovalDecisionParams,
                params,
            )
            await store_idempotency(request_id, "decide_patch_approval", result)
            return result

        @server.tool(
            name="delete_policy",
            description="Permanently delete an Automox policy by ID.",
            annotations={"destructiveHint": True},
        )
        async def delete_policy(
            policy_id: int,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "delete_policy")
            if cached is not None:
                return cached

            params = {"policy_id": policy_id}
            result = await _call(
                workflows.delete_policy,
                DeletePolicyToolParams,
                params,
            )
            await store_idempotency(request_id, "delete_policy", result)
            return result

        @server.tool(
            name="clone_policy",
            description=(
                "Clone an existing Automox policy. Creates a copy with an optional "
                "new name and server group assignments."
            ),
            annotations={"destructiveHint": True},
        )
        async def clone_policy(
            policy_id: int,
            name: str | None = None,
            server_groups: list[int] | None = None,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "clone_policy")
            if cached is not None:
                return cached

            params: dict[str, Any] = {"policy_id": policy_id}
            if name is not None:
                params["name"] = name
            if server_groups is not None:
                params["server_groups"] = server_groups
            result = await _call(
                workflows.clone_policy,
                ClonePolicyParams,
                params,
            )
            await store_idempotency(request_id, "clone_policy", result)
            return result

        @server.tool(
            name="apply_policy_changes",
            description="Create or update Automox policies with automatic format correction.",
            annotations={"destructiveHint": True},
        )
        async def apply_policy_changes_tool(
            operations: list[dict[str, Any]],
            preview: bool | None = False,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "apply_policy_changes")
            if cached is not None:
                return cached

            normalized_operations = workflows.normalize_policy_operations_input(operations)
            params = {
                "operations": normalized_operations,
                "preview": preview,
            }
            result = await _call(
                workflows.apply_policy_changes,
                PolicyChangeRequestParams,
                params,
            )
            await store_idempotency(request_id, "apply_policy_changes", result)
            return result

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
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "execute_policy_now")
            if cached is not None:
                return cached

            params = {
                "policy_id": policy_id,
                "action": action,
                "device_id": device_id,
            }
            result = await _call(
                workflows.execute_policy,
                ExecutePolicyParams,
                params,
            )
            await store_idempotency(request_id, "execute_policy_now", result)
            return result


__all__ = ["register"]
