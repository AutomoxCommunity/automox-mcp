"""Report-related tools for Automox MCP."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from .. import workflows
from ..client import AutomoxClient
from ..schemas import (
    GetNeedsAttentionReportParams,
    GetPrepatchReportParams,
)
from ..utils.tooling import (
    call_tool_workflow,
    maybe_format_markdown,
)


def register(server: FastMCP, *, read_only: bool = False, client: AutomoxClient) -> None:
    """Register report-related tools."""

    @server.tool(
        name="prepatch_report",
        description=(
            "Retrieve the Automox pre-patch readiness report showing devices "
            "with pending patches before the next scheduled patch window. "
            "Per-device 'highest_severity' distinguishes 'no_known_cves' (patches "
            "carry no associated CVE — benign) from 'unknown' (severity "
            "undetermined). 'compliant' follows the platform rule: a device is "
            "non-compliant only when a policy needs remediation; pending work "
            "alone does not count against it."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def prepatch_report(
        group_id: int | None = None,
        limit: int | None = None,
        offset: int | None = None,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        params = {
            "group_id": group_id,
            "limit": limit,
            "offset": offset,
        }
        result = await call_tool_workflow(
            client,
            workflows.get_prepatch_report,
            params,
            params_model=GetPrepatchReportParams,
            inject_org_id=True,
        )

        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="noncompliant_report",
        description=(
            "Retrieve the Automox non-compliant devices report showing devices "
            "that need attention due to policy failures or missing patches. Each "
            "failing policy includes 'reason_for_fail' (upstream failure text, "
            "may be truncated), 'severity', and 'type' so you can state why a "
            "device is non-compliant and prioritize across devices."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def noncompliant_report(
        group_id: int | None = None,
        limit: int | None = None,
        offset: int | None = None,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        params = {
            "group_id": group_id,
            "limit": limit,
            "offset": offset,
        }
        result = await call_tool_workflow(
            client,
            workflows.get_noncompliant_report,
            params,
            params_model=GetNeedsAttentionReportParams,
            inject_org_id=True,
        )

        return maybe_format_markdown(result, output_format)


__all__ = ["register"]
