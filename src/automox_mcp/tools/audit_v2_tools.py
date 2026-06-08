"""Audit Service v2 (OCSF) tools for Automox MCP."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from ..client import AutomoxClient
from ..schemas import AuditEventsOcsfParams
from ..utils.tooling import (
    ToolReturn,
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
            "Filter by date (required) and event type name. "
            "The `category_name` filter is applied client-side against the event "
            "`type_name` prefix: the upstream events do NOT carry a `category_name` "
            "field, only an integer `category_uid` that maps 1:N across categories, "
            "so category filtering matches the `type_name` label prefix "
            "(authentication/entity_management/web_resource_activity are "
            "live-verified prefixes; account_change/user_access are spec-derived and "
            "unverified live). An unmappable category token leaves results unfiltered "
            "and sets `metadata.applied_filters.category_name_matched=false` (so an "
            "empty result is never mistaken for 'no activity'); "
            "`metadata.events_before_filter` reports the unfiltered count. "
            "`category_uid`/`type_uid`/`class_uid`/`activity_id` are raw OCSF taxonomy "
            "integers with no decode table in the upstream spec — prefer the "
            "human-readable sibling strings `type_name` and `activity`. "
            "Uses cursor-based pagination for large result sets. "
            "Event `time` is an ISO 8601 UTC string (converted from the upstream "
            "epoch-seconds value). The `date` parameter selects events by event date; "
            "the timezone of that date boundary is not stated by the upstream spec "
            "(unverified). `severity`/`status` labels follow the OCSF scales "
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
    ) -> ToolReturn:
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
