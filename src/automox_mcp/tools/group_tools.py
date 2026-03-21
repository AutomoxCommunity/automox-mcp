"""Server group management tools for Automox MCP."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, ValidationError

from .. import workflows
from ..client import AutomoxAPIError, AutomoxClient
from ..schemas import (
    CreateServerGroupParams,
    DeleteServerGroupParams,
    GetServerGroupParams,
    ListServerGroupsParams,
    OrgIdContextMixin,
    OrgIdRequiredMixin,
    UpdateServerGroupParams,
)
from ..utils.tooling import (
    RateLimitError,
    as_tool_response,
    check_idempotency,
    enforce_rate_limit,
    format_as_markdown_table,
    format_error,
    store_idempotency,
)


def register(server: FastMCP, *, read_only: bool = False, client: AutomoxClient) -> None:
    """Register server group management tools."""

    async def _call(
        func: Callable[..., Awaitable[dict[str, Any]]],
        params_model: type[BaseModel],
        raw_params: dict[str, Any],
        *,
        inject_org_id: bool = False,
    ) -> dict[str, Any]:
        try:
            await enforce_rate_limit()
            client_org_id = client.org_id
            params = dict(raw_params)
            if issubclass(params_model, (OrgIdContextMixin, OrgIdRequiredMixin)):
                params.setdefault("org_id", client_org_id)
                if params.get("org_id") is None:
                    raise ToolError(
                        "org_id required - set AUTOMOX_ORG_ID or pass org_id explicitly."
                    )
            model = params_model(**params)
            payload = model.model_dump(mode="python", exclude_none=True)
            if isinstance(model, (OrgIdContextMixin, OrgIdRequiredMixin)):
                payload["org_id"] = model.org_id
            elif inject_org_id:
                if client_org_id is None:
                    raise ToolError(
                        "org_id required - set AUTOMOX_ORG_ID or pass org_id explicitly."
                    )
                payload["org_id"] = client_org_id
            result: dict[str, Any] = await func(client, **payload)
        except (ValidationError, ValueError) as exc:
            raise ToolError(str(exc)) from exc
        except RateLimitError as exc:
            raise ToolError(str(exc)) from exc
        except AutomoxAPIError as exc:
            raise ToolError(format_error(exc)) from exc
        except ToolError:
            raise
        except Exception as exc:
            raise ToolError(f"Unexpected error: {type(exc).__name__}: {exc}") from exc
        return as_tool_response(result)

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
        result = await _call(
            workflows.list_server_groups,
            ListServerGroupsParams,
            params,
            inject_org_id=True,
        )

        if output_format == "markdown":
            data = result.get("data", {})
            for _key, value in data.items():
                if isinstance(value, list) and value:
                    return format_as_markdown_table(value)
            return format_as_markdown_table([])

        return result

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
        return await _call(
            workflows.get_server_group,
            GetServerGroupParams,
            params,

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
            cached = check_idempotency(request_id, "create_server_group")
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
            result = await _call(
                workflows.create_server_group,
                CreateServerGroupParams,
                params,
                inject_org_id=True,
            )
            store_idempotency(request_id, "create_server_group", result)
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
            cached = check_idempotency(request_id, "update_server_group")
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
            result = await _call(
                workflows.update_server_group,
                UpdateServerGroupParams,
                params,
                inject_org_id=True,
            )
            store_idempotency(request_id, "update_server_group", result)
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
            cached = check_idempotency(request_id, "delete_server_group")
            if cached is not None:
                return cached

            params = {
                "group_id": group_id,
            }
            result = await _call(
                workflows.delete_server_group,
                DeleteServerGroupParams,
                params,
            )
            store_idempotency(request_id, "delete_server_group", result)
            return result


__all__ = ["register"]
