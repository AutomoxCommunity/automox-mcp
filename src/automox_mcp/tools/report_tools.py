"""Report-related tools for Automox MCP."""

from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)


def register(server: FastMCP, *, read_only: bool = False, client: AutomoxClient) -> None:
    """Register report-related tools."""

    @server.tool(
        name="prepatch_report",
        description=(
            "Retrieve the Automox pre-patch readiness report showing devices "
            "with pending patches before the next scheduled patch window."
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
            "that need attention due to policy failures or missing patches."
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
