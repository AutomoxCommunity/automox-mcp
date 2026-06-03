"""Policy-related tools for Automox MCP."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from .. import workflows
from ..client import AutomoxClient
from ..schemas import (
    ClonePolicyParams,
    DeletePolicyToolParams,
    ExecutePolicyParams,
    GetPolicyStatsParams,
    ListDevicesForPoliciesParams,
    PatchApprovalDecisionParams,
    PatchApprovalSummaryParams,
    PolicyChangeRequestParams,
    PolicyDetailParams,
    PolicyDeviceFilterPreviewParams,
    PolicyExecutionTimelineParams,
    PolicyHealthSummaryParams,
    PolicySummaryParams,
    RunDetailParams,
    UploadPolicyFileParams,
)
from ..utils.tooling import (
    call_tool_workflow,
    check_idempotency,
    is_stdio_transport,
    is_upload_policy_file_allowed,
    maybe_format_markdown,
    release_idempotency,
    store_idempotency,
)
from ..utils.upload import get_upload_allowed_dirs


def register(server: FastMCP, *, read_only: bool = False, client: AutomoxClient) -> None:
    """Register policy-related tools."""

    @server.tool(
        name="policy_health_overview",
        description="Summarize recent Automox policy activity.",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
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
        return await call_tool_workflow(
            client,
            workflows.summarize_policy_activity,
            params,
            params_model=PolicyHealthSummaryParams,
            org_uuid_field="org_uuid",
            allow_account_uuid=True,
        )

    @server.tool(
        name="policy_execution_timeline",
        description="Review recent executions for a policy.",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
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
        return await call_tool_workflow(
            client,
            workflows.summarize_policy_execution_history,
            params,
            params_model=PolicyExecutionTimelineParams,
            org_uuid_field="org_uuid",
            allow_account_uuid=True,
        )

    @server.tool(
        name="policy_run_results",
        description="Retrieve per-device results and output for a specific policy execution token.",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
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
        return await call_tool_workflow(
            client,
            workflows.describe_policy_run_result,
            params,
            params_model=RunDetailParams,
            org_uuid_field="org_uuid",
            allow_account_uuid=True,
        )

    @server.tool(
        name="policy_catalog",
        description="List Automox policies with type and status summaries.",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def policy_catalog(
        limit: int | None = 20,
        page: int | None = 0,
        include_inactive: bool | None = False,
        include_stats: bool | None = False,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        params = {
            "limit": limit,
            "page": page,
            "include_inactive": include_inactive,
            "include_stats": include_stats,
        }
        result = await call_tool_workflow(
            client,
            workflows.summarize_policies,
            params,
            params_model=PolicySummaryParams,
        )

        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="policy_detail",
        description="Retrieve configuration and recent history for a policy.",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def policy_detail(
        policy_id: int,
        include_recent_runs: int | None = 5,
    ) -> dict[str, Any]:
        params = {
            "policy_id": policy_id,
            "include_recent_runs": include_recent_runs,
        }
        return await call_tool_workflow(
            client,
            workflows.describe_policy,
            params,
            params_model=PolicyDetailParams,
        )

    @server.tool(
        name="policy_compliance_stats",
        description=(
            "Retrieve per-policy compliance statistics showing compliant vs "
            "non-compliant device counts and compliance rates for the organization."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def policy_compliance_stats() -> dict[str, Any]:
        return await call_tool_workflow(
            client,
            workflows.get_policy_compliance_stats,
            {},
            params_model=GetPolicyStatsParams,
        )

    @server.tool(
        name="patch_approvals_summary",
        description="Summarize pending patch approvals and their severity.",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
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
        result = await call_tool_workflow(
            client,
            workflows.summarize_patch_approvals,
            params,
            params_model=PatchApprovalSummaryParams,
        )

        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="preview_policy_device_filters",
        description=(
            "Dry-run: preview which devices a policy's device filters and/or "
            "server groups would target, before creating or updating the policy. "
            "Read-only — nothing is created or changed."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def preview_policy_device_filters(
        device_filters: list[dict[str, Any]] | None = None,
        server_groups: list[int] | None = None,
        page: int | None = None,
        limit: int | None = None,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await call_tool_workflow(
            client,
            workflows.preview_policy_device_filters,
            {
                "device_filters": device_filters,
                "server_groups": server_groups,
                "page": page,
                "limit": limit,
            },
            params_model=PolicyDeviceFilterPreviewParams,
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="list_devices_for_policies",
        description=(
            "List the devices currently targeted by one or more policies (by "
            "policy UUID) — blast-radius assessment before executing or changing "
            "a policy. Read-only."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def list_devices_for_policies(
        policies: list[str],
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await call_tool_workflow(
            client,
            workflows.list_devices_for_policies,
            {"policies": policies},
            params_model=ListDevicesForPoliciesParams,
        )
        return maybe_format_markdown(result, output_format)

    if not read_only:

        @server.tool(
            name="decide_patch_approval",
            description="Approve or reject an Automox patch approval request.",
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": False,
                "openWorldHint": True,
            },
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
            try:
                result = await call_tool_workflow(
                    client,
                    workflows.resolve_patch_approval,
                    params,
                    params_model=PatchApprovalDecisionParams,
                )
            except BaseException:
                await release_idempotency(request_id, "decide_patch_approval")
                raise
            await store_idempotency(request_id, "decide_patch_approval", result)
            return result

        @server.tool(
            name="delete_policy",
            description="Permanently delete an Automox policy by ID.",
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": True,
                "openWorldHint": True,
            },
        )
        async def delete_policy(
            policy_id: int,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "delete_policy")
            if cached is not None:
                return cached

            params = {"policy_id": policy_id}
            try:
                result = await call_tool_workflow(
                    client,
                    workflows.delete_policy,
                    params,
                    params_model=DeletePolicyToolParams,
                )
            except BaseException:
                await release_idempotency(request_id, "delete_policy")
                raise
            await store_idempotency(request_id, "delete_policy", result)
            return result

        @server.tool(
            name="clone_policy",
            description=(
                "Clone an existing Automox policy. By default creates an in-org copy "
                "with an optional new name and server group assignments. Pass "
                "target_zone_ids to instead clone a patch policy into one or more "
                "zones/orgs in a single server-side call (patch policies only; "
                "mutually exclusive with name/server_groups)."
            ),
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": False,
                "openWorldHint": True,
            },
        )
        async def clone_policy(
            policy_id: int,
            name: str | None = None,
            server_groups: list[int] | None = None,
            target_zone_ids: list[str] | None = None,
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
            if target_zone_ids is not None:
                params["target_zone_ids"] = target_zone_ids
            try:
                result = await call_tool_workflow(
                    client,
                    workflows.clone_policy,
                    params,
                    params_model=ClonePolicyParams,
                )
            except BaseException:
                await release_idempotency(request_id, "clone_policy")
                raise
            await store_idempotency(request_id, "clone_policy", result)
            return result

        @server.tool(
            name="apply_policy_changes",
            description="Create or update Automox policies with automatic format correction.",
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": False,
                "openWorldHint": True,
            },
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
            try:
                result = await call_tool_workflow(
                    client,
                    workflows.apply_policy_changes,
                    params,
                    params_model=PolicyChangeRequestParams,
                )
            except BaseException:
                await release_idempotency(request_id, "apply_policy_changes")
                raise
            await store_idempotency(request_id, "apply_policy_changes", result)
            return result

        @server.tool(
            name="execute_policy_now",
            description=(
                "Execute an Automox policy immediately for remediation "
                "(all devices or specific device)."
            ),
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": False,
                "openWorldHint": True,
            },
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
            try:
                result = await call_tool_workflow(
                    client,
                    workflows.execute_policy,
                    params,
                    params_model=ExecutePolicyParams,
                )
            except BaseException:
                await release_idempotency(request_id, "execute_policy_now")
                raise
            await store_idempotency(request_id, "execute_policy_now", result)
            return result

        # Local-file installer upload: reads a file off disk, so it is opt-in
        # (AUTOMOX_MCP_ALLOW_UPLOAD_POLICY_FILE), restricted to a directory
        # allowlist (AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS, must be non-empty), and
        # local-transport only. main() additionally refuses to start a remote
        # transport while the flag is on, so the tool can never be served
        # remotely even if this env-based stdio check is somehow bypassed.
        if is_upload_policy_file_allowed() and is_stdio_transport() and get_upload_allowed_dirs():

            @server.tool(
                name="upload_policy_file",
                description=(
                    "Upload an installer file to a Required Software policy from the "
                    "local filesystem. `file_path` must be an absolute path resolving "
                    "inside an AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS directory; the bytes "
                    "stream straight to Automox and never pass through the model. "
                    "Requires AUTOMOX_MCP_ALLOW_UPLOAD_POLICY_FILE=true, a configured "
                    "AUTOMOX_MCP_UPLOAD_ALLOWED_DIRS, and a local (stdio) transport."
                ),
                annotations={
                    "readOnlyHint": False,
                    "destructiveHint": True,
                    "idempotentHint": False,
                    "openWorldHint": True,
                },
            )
            async def upload_policy_file(
                policy_id: int,
                file_path: str,
                request_id: str | None = None,
            ) -> dict[str, Any]:
                cached = await check_idempotency(request_id, "upload_policy_file")
                if cached is not None:
                    return cached

                params = {"policy_id": policy_id, "file_path": file_path}
                try:
                    result = await call_tool_workflow(
                        client,
                        workflows.upload_policy_file,
                        params,
                        params_model=UploadPolicyFileParams,
                    )
                except BaseException:
                    await release_idempotency(request_id, "upload_policy_file")
                    raise
                await store_idempotency(request_id, "upload_policy_file", result)
                return result


__all__ = ["register"]
