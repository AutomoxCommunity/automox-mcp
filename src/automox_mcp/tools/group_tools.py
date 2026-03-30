"""Server group management tools for Automox MCP."""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP

from .. import workflows
from ..client import AutomoxClient
from ..schemas import (
    CreateServerGroupParams,
    DeleteServerGroupParams,
    GetServerGroupParams,
    ListServerGroupsParams,
    UpdateServerGroupParams,
)
from ..utils.tooling import (
    call_tool_workflow,
    check_idempotency,
    maybe_format_markdown,
    store_idempotency,
)

logger = logging.getLogger(__name__)


def register(server: FastMCP, *, read_only: bool = False, client: AutomoxClient) -> None:
    """Register server group management tools."""

    @server.tool(
        name="list_server_groups",
        description=(
            "List all Automox server groups with their device counts and assigned policies."
        ),
    )
    async def list_server_groups(
        page: int | None = None,
        limit: int | None = None,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        params = {
            "page": page,
            "limit": limit,
        }
        result = await call_tool_workflow(
            client,
            workflows.list_server_groups,
            params,
            params_model=ListServerGroupsParams,
            inject_org_id=True,
        )

        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="get_server_group",
        description="Get detailed information about a specific Automox server group.",
    )
    async def get_server_group(
        group_id: int,
    ) -> dict[str, Any]:
        params = {
            "group_id": group_id,
        }
        return await call_tool_workflow(
            client,
            workflows.get_server_group,
            params,
            params_model=GetServerGroupParams,
            inject_org_id=True,
        )

    if not read_only:

        @server.tool(
            name="create_server_group",
            description="Create a new Automox server group.",
            annotations={"destructiveHint": True},
        )
        async def create_server_group(
            name: str,
            refresh_interval: int,
            parent_server_group_id: int,
            ui_color: str | None = None,
            notes: str | None = None,
            policies: list[int] | None = None,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "create_server_group")
            if cached is not None:
                return cached

            params = {
                "name": name,
                "refresh_interval": refresh_interval,
                "parent_server_group_id": parent_server_group_id,
                "ui_color": ui_color,
                "notes": notes,
                "policies": policies,
            }
            result = await call_tool_workflow(
                client,
                workflows.create_server_group,
                params,
                params_model=CreateServerGroupParams,
                inject_org_id=True,
            )
            await store_idempotency(request_id, "create_server_group", result)
            return result

        @server.tool(
            name="update_server_group",
            description="Update an existing Automox server group.",
            annotations={"destructiveHint": True},
        )
        async def update_server_group(
            group_id: int,
            name: str,
            refresh_interval: int,
            parent_server_group_id: int,
            ui_color: str | None = None,
            notes: str | None = None,
            policies: list[int] | None = None,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "update_server_group")
            if cached is not None:
                return cached

            params = {
                "group_id": group_id,
                "name": name,
                "refresh_interval": refresh_interval,
                "parent_server_group_id": parent_server_group_id,
                "ui_color": ui_color,
                "notes": notes,
                "policies": policies,
            }
            result = await call_tool_workflow(
                client,
                workflows.update_server_group,
                params,
                params_model=UpdateServerGroupParams,
                inject_org_id=True,
            )
            await store_idempotency(request_id, "update_server_group", result)
            return result

        @server.tool(
            name="delete_server_group",
            description="Delete an Automox server group permanently.",
            annotations={"destructiveHint": True},
        )
        async def delete_server_group(
            group_id: int,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "delete_server_group")
            if cached is not None:
                return cached

            params = {
                "group_id": group_id,
            }
            result = await call_tool_workflow(
                client,
                workflows.delete_server_group,
                params,
                params_model=DeleteServerGroupParams,
            )
            await store_idempotency(request_id, "delete_server_group", result)
            return result


__all__ = ["register"]
