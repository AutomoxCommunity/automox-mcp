"""Audit Service v2 (OCSF) tools for Automox MCP."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from ..client import AutomoxClient
from ..schemas import AuditEventsOcsfParams
from ..utils.tooling import (
    call_tool_workflow,
    maybe_format_markdown,
)
from ..workflows.audit_v2 import audit_events_ocsf as _audit_events_ocsf


def register(server: FastMCP, *, read_only: bool = False, client: AutomoxClient) -> None:
    """Register audit service v2 (OCSF) tools."""

    @server.tool(
        name="audit_events_ocsf",
        description=(
            "Query OCSF-formatted audit events from the Automox Audit Service v2. "
            "Supports filtering by date, event category (authentication, account_change, "
            "entity_management, user_access, web_resource_activity), and event type name. "
            "Uses cursor-based pagination for large result sets. "
            "Event `time` is an ISO 8601 UTC string (converted from the upstream "
            "epoch-seconds value). `severity`/`status` labels follow the OCSF scales "
            "(severity: informational/low/medium/high/critical/fatal; status: "
            "success/failure/other) and are filled from `severity_id`/`status_id` "
            "when the upstream omits the string. "
            "Permissions: as of 2025-10-27 the upstream endpoint requires the API key "
            "to have BOTH `organization:manage` and `users:read` scopes; keys missing "
            "either scope return 403."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
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
        result = await call_tool_workflow(
            client, _audit_events_ocsf, kwargs, params_model=AuditEventsOcsfParams
        )
        return maybe_format_markdown(result, output_format)


__all__ = ["register"]
