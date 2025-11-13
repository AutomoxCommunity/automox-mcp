"""Account/user management tools for Automox MCP."""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, ValidationError

from .. import workflows
from ..client import AutomoxAPIError, AutomoxClient
from ..schemas import InviteUserParams, RemoveUserFromAccountParams, ZoneAssignment
from ..utils.tooling import (
    RateLimitError,
    as_tool_response,
    enforce_rate_limit,
    format_error,
)


def register(server: FastMCP) -> None:
    """Register account-related tools."""

    async def _call(
        func: Callable[..., Awaitable[dict[str, Any]]],
        params_model: type[BaseModel] | None,
        raw_params: dict[str, Any],
        api: str | None = None,
    ) -> dict[str, Any]:
        try:
            await enforce_rate_limit(api)
            params = dict(raw_params)
            payload = params
            if params_model is not None:
                model = params_model(**params)
                payload = model.model_dump(mode="python", exclude_none=True)
            async with AutomoxClient(default_api=api) as client:
                result: dict[str, Any] = await func(client, **payload)
        except (ValidationError, ValueError) as exc:
            raise ToolError(str(exc)) from exc
        except RateLimitError as exc:
            raise ToolError(str(exc)) from exc
        except AutomoxAPIError as exc:
            raise ToolError(format_error(exc)) from exc
        return as_tool_response(result)

    def _resolve_account_id(explicit: str | None = None) -> str:
        if explicit:
            return explicit
        env_value = os.environ.get("AUTOMOX_ACCOUNT_UUID")
        if not env_value:
            raise ToolError(
                "AUTOMOX_ACCOUNT_UUID environment variable is required for account tools. "
                "Set it in the environment or pass account_id explicitly."
            )
        return env_value

    @server.tool(
        name="invite_user_to_account",
        description="Invite a user to the Automox account with optional zone assignments.",
        annotations={"destructiveHint": True},
    )
    async def invite_user_to_account(
        email: str,
        account_rbac_role: Literal["global-admin", "no-global-access"],
        zone_assignments: list[ZoneAssignment] | None = None,
    ) -> dict[str, Any]:
        params = {
            "account_id": _resolve_account_id(None),
            "email": email,
            "account_rbac_role": account_rbac_role,
            "zone_assignments": zone_assignments,
        }
        return await _call(
            workflows.invite_user_to_account,
            InviteUserParams,
            params,
            api="console",
        )

    @server.tool(
        name="remove_user_from_account",
        description="Remove a user from the Automox account by UUID.",
        annotations={"destructiveHint": True},
    )
    async def remove_user_from_account(
        user_id: str,
    ) -> dict[str, Any]:
        params = {
            "account_id": _resolve_account_id(None),
            "user_id": user_id,
        }
        return await _call(
            workflows.remove_user_from_account,
            RemoveUserFromAccountParams,
            params,
            api="console",
        )


__all__ = ["register"]
