"""Event-related tools for Automox MCP."""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP

from .. import workflows
from ..client import AutomoxClient
from ..schemas import GetEventsParams
from ..utils.tooling import (
    call_tool_workflow,
    maybe_format_markdown,
)

logger = logging.getLogger(__name__)


def register(server: FastMCP, *, read_only: bool = False, client: AutomoxClient) -> None:
    """Register event-related tools."""

    @server.tool(
        name="list_events",
        description=(
            "List Automox organization events with optional filters by policy, "
            "device, user, event name, or date range."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def list_events(
        page: int | None = None,
        limit: int | None = None,
        count_only: bool | None = None,
        policy_id: int | None = None,
        server_id: int | None = None,
        user_id: int | None = None,
        event_name: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        params = {
            "page": page,
            "limit": limit,
            "count_only": count_only,
            "policy_id": policy_id,
            "server_id": server_id,
            "user_id": user_id,
            "event_name": event_name,
            "start_date": start_date,
            "end_date": end_date,
        }
        result = await call_tool_workflow(
            client,
            workflows.list_events,
            params,
            params_model=GetEventsParams,
            inject_org_id=True,
        )

        return maybe_format_markdown(result, output_format)


__all__ = ["register"]
