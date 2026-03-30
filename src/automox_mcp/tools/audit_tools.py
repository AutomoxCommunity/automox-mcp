"""Audit trail tools for Automox MCP."""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP

from .. import workflows
from ..client import AutomoxClient
from ..schemas import AuditTrailEventsParams
from ..utils.tooling import (
    call_tool_workflow,
    maybe_format_markdown,
)

logger = logging.getLogger(__name__)


def register(server: FastMCP, *, read_only: bool = False, client: AutomoxClient) -> None:
    """Register audit trail-related tools."""

    @server.tool(
        name="audit_trail_user_activity",
        description="Retrieve Automox audit trail events performed by a user on a specific date.",
    )
    async def audit_trail_user_activity(
        date: str,
        actor_email: str | None = None,
        actor_uuid: str | None = None,
        actor_name: str | None = None,
        cursor: str | None = None,
        limit: int | None = None,
        include_raw_events: bool | None = False,
        org_uuid: str | None = None,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        params = {
            "date": date,
            "actor_email": actor_email,
            "actor_uuid": actor_uuid,
            "actor_name": actor_name,
            "cursor": cursor,
            "limit": limit,
            "include_raw_events": include_raw_events,
            "org_uuid": org_uuid,
        }
        result = await call_tool_workflow(
            client,
            workflows.audit_trail_user_activity,
            params,
            params_model=AuditTrailEventsParams,
        )

        return maybe_format_markdown(result, output_format)


__all__ = ["register"]
