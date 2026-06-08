"""Vulnerability Sync / Remediations tools for Automox MCP."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from fastmcp.apps import AppConfig, ResourceCSP

from ..client import AutomoxClient
from ..resources.remediation_apply_app import REMEDIATION_APPLY_APP_URI
from ..schemas import (
    ActionSetSolutionsResult,
    DeleteActionSetParams,
    DeleteActionSetsBulkParams,
    GetActionSetIssuesParams,
    GetActionSetParams,
    GetActionSetSolutionsParams,
    GetActionSetUploadFormatsParams,
    ListActionSetsParams,
    RunRemediationActionsParams,
    UploadActionSetParams,
)
from ..utils.tooling import (
    ToolReturn,
    call_tool_workflow,
    check_idempotency,
    is_remediation_allowed,
    maybe_format_markdown,
    release_idempotency,
    store_idempotency,
)
from ..workflows.vuln_sync import (
    apply_remediation_actions as _apply_remediation_actions,
)
from ..workflows.vuln_sync import (
    delete_action_set as _delete_action_set,
)
from ..workflows.vuln_sync import (
    delete_action_sets_bulk as _delete_action_sets_bulk,
)
from ..workflows.vuln_sync import (
    get_action_set_detail as _get_action_set_detail,
)
from ..workflows.vuln_sync import (
    get_action_set_issues as _get_action_set_issues,
)
from ..workflows.vuln_sync import (
    get_action_set_solutions as _get_action_set_solutions,
)
from ..workflows.vuln_sync import (
    get_upload_formats as _get_upload_formats,
)
from ..workflows.vuln_sync import (
    list_remediation_action_sets as _list_remediation_action_sets,
)
from ..workflows.vuln_sync import (
    upload_action_set as _upload_action_set,
)


def register(server: FastMCP, *, read_only: bool = False, client: AutomoxClient) -> None:
    """Register vulnerability sync / remediations tools."""

    @server.tool(
        name="list_remediation_action_sets",
        description=(
            "List vulnerability remediation action sets for the organization. "
            "Shows imported vulnerability data and remediation tracking."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def list_remediation_action_sets(
        output_format: str | None = "json",
    ) -> ToolReturn:
        result = await call_tool_workflow(
            client,
            _list_remediation_action_sets,
            {},
            params_model=ListActionSetsParams,
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="get_action_set_detail",
        description=(
            "Get details for a specific vulnerability remediation action set. The "
            "`status` field is a processing-lifecycle string; observed live "
            "(2026-06-06) as building -> ready, with 'ready' the confirmed terminal "
            "value. 'active' is the spec example only and was not reproduced. See "
            "metadata.field_notes."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_action_set_detail(
        action_set_id: int,
        output_format: str | None = "json",
    ) -> ToolReturn:
        result = await call_tool_workflow(
            client,
            _get_action_set_detail,
            {"action_set_id": action_set_id},
            params_model=GetActionSetParams,
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="get_action_set_issues",
        description=(
            "Get vulnerability issues (CVEs) associated with an action set. "
            "Shows which vulnerabilities are being tracked for remediation."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_action_set_issues(
        action_set_id: int,
        output_format: str | None = "json",
    ) -> ToolReturn:
        result = await call_tool_workflow(
            client,
            _get_action_set_issues,
            {"action_set_id": action_set_id},
            params_model=GetActionSetIssuesParams,
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="get_action_set_solutions",
        description=(
            "Get solutions for a vulnerability action set. Shows recommended patches "
            "or configurations to resolve vulnerabilities. Per-vulnerability `severity` "
            "and per-device `status` are coded strings with no API-enumerated value set "
            "(severity scale/ceiling spec-derived and unverified live; device status "
            "observed live transitioning not-started -> in_progress, note the mixed "
            "hyphen/underscore separators) — see metadata.field_notes."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
        output_schema=ActionSetSolutionsResult.model_json_schema(),
        # Write-flow MCP App (#181): Apps-capable hosts render the remediation-apply
        # review UI from this tool's structured output (solutions + affected devices).
        # The UI drives the gated apply_remediation_actions (patch-now) via the host
        # CallTool bridge; the env gate remains the control. Self-contained UI → empty CSP.
        app=AppConfig(resourceUri=REMEDIATION_APPLY_APP_URI, csp=ResourceCSP()),
    )
    async def get_action_set_solutions(
        action_set_id: int,
        output_format: str | None = "json",
    ) -> ToolReturn:
        result = await call_tool_workflow(
            client,
            _get_action_set_solutions,
            {"action_set_id": action_set_id},
            params_model=GetActionSetSolutionsParams,
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="get_upload_formats",
        description="Get supported CSV upload formats for vulnerability remediation action sets.",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def get_upload_formats(
        output_format: str | None = "json",
    ) -> ToolReturn:
        result = await call_tool_workflow(
            client,
            _get_upload_formats,
            {},
            params_model=GetActionSetUploadFormatsParams,
        )
        return maybe_format_markdown(result, output_format)

    if not read_only:

        @server.tool(
            name="upload_action_set",
            description=(
                "Upload a CSV-based vulnerability remediation action set. Provide "
                "the CSV as text in `csv_content`; `source` selects the format "
                "(generic | qualys | tenable | crowd-strike | rapid7). Call "
                "get_upload_formats first to see the required columns per source. "
                "The `filename` becomes the action set's display name. Returns the "
                "created action set (status is usually 'building' — processing is "
                "async)."
            ),
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": False,
                "openWorldHint": True,
            },
        )
        async def upload_action_set(
            csv_content: str,
            source: str = "generic",
            filename: str = "action-set.csv",
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "upload_action_set")
            if cached is not None:
                return cached
            result = await call_tool_workflow(
                client,
                _upload_action_set,
                {"csv_content": csv_content, "source": source, "filename": filename},
                params_model=UploadActionSetParams,
            )
            await store_idempotency(request_id, "upload_action_set", result)
            return result

        @server.tool(
            name="delete_action_set",
            description=(
                "Delete a single vulnerability remediation action set by ID. "
                "Action sets are console metadata (not endpoint state) and are "
                "reconstructable by re-uploading the source CSV."
            ),
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": True,
                "openWorldHint": True,
            },
        )
        async def delete_action_set(
            action_set_id: int,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "delete_action_set")
            if cached is not None:
                return cached
            try:
                result = await call_tool_workflow(
                    client,
                    _delete_action_set,
                    {"action_set_id": action_set_id},
                    params_model=DeleteActionSetParams,
                )
            except BaseException:
                await release_idempotency(request_id, "delete_action_set")
                raise
            await store_idempotency(request_id, "delete_action_set", result)
            return result

        @server.tool(
            name="delete_action_sets_bulk",
            description=(
                "Delete multiple vulnerability remediation action sets by ID (up to "
                "100) in one atomic call. Action sets are reconstructable by "
                "re-uploading the source CSV."
            ),
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": True,
                "openWorldHint": True,
            },
        )
        async def delete_action_sets_bulk(
            action_set_ids: list[int],
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "delete_action_sets_bulk")
            if cached is not None:
                return cached
            try:
                result = await call_tool_workflow(
                    client,
                    _delete_action_sets_bulk,
                    {"action_set_ids": action_set_ids},
                    params_model=DeleteActionSetsBulkParams,
                )
            except BaseException:
                await release_idempotency(request_id, "delete_action_sets_bulk")
                raise
            await store_idempotency(request_id, "delete_action_sets_bulk", result)
            return result

        # Remediation EXECUTION is opt-in beyond write mode: it immediately
        # patches/runs worklets on endpoints. Gated by AUTOMOX_MCP_ALLOW_APPLY_REMEDIATION_ACTIONS.
        if is_remediation_allowed():

            @server.tool(
                name="apply_remediation_actions",
                description=(
                    "Execute remediation actions on devices NOW — patch-now or "
                    "patch-with-worklet — for a remediation action set. This immediately "
                    "changes endpoint state (async, returns 202). Requires "
                    "AUTOMOX_MCP_ALLOW_APPLY_REMEDIATION_ACTIONS=true. Provide explicit "
                    "solution_id and device IDs per action; there is no 'all devices' shortcut."
                ),
                annotations={
                    "readOnlyHint": False,
                    "destructiveHint": True,
                    "idempotentHint": False,
                    "openWorldHint": True,
                },
            )
            async def apply_remediation_actions(
                action_set_id: int,
                actions: list[dict[str, Any]],
                request_id: str | None = None,
            ) -> dict[str, Any]:
                cached = await check_idempotency(request_id, "apply_remediation_actions")
                if cached is not None:
                    return cached
                try:
                    result = await call_tool_workflow(
                        client,
                        _apply_remediation_actions,
                        {"action_set_id": action_set_id, "actions": actions},
                        params_model=RunRemediationActionsParams,
                    )
                except BaseException:
                    await release_idempotency(request_id, "apply_remediation_actions")
                    raise
                await store_idempotency(request_id, "apply_remediation_actions", result)
                return result


__all__ = ["register"]
