"""Audit Service v2 (OCSF) tools for Automox MCP."""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from ..client import AutomoxClient
from ..utils.tooling import (
    call_tool_workflow,
    maybe_format_markdown,
)
from ..workflows.audit_v2 import audit_events_ocsf as _audit_events_ocsf

logger = logging.getLogger(__name__)


def register(server: FastMCP, *, read_only: bool = False, client: AutomoxClient) -> None:
    """Register audit service v2 (OCSF) tools."""

    @server.tool(
        name="audit_events_ocsf",
        description=(
            "Query OCSF-formatted audit events from the Automox Audit Service v2. "
            "Supports filtering by date, event category (authentication, account_change, "
            "entity_management, user_access, web_resource_activity), and event type name. "
            "Uses cursor-based pagination for large result sets."
        ),
    )
    async def audit_events_ocsf(
        date: str,
        category_name: str | None = None,
        type_name: str | None = None,
        cursor: str | None = None,
        limit: int | None = None,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "date": date,
            "category_name": category_name,
            "type_name": type_name,
            "cursor": cursor,
            "limit": limit,
        }
        kwargs.setdefault("org_id", client.org_id)
        if kwargs.get("org_id") is None:
            raise ToolError("org_id required - set AUTOMOX_ORG_ID or pass org_id explicitly.")
        result = await call_tool_workflow(client, _audit_events_ocsf, kwargs)
        return maybe_format_markdown(result, output_format)


__all__ = ["register"]
