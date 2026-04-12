"""Account/user management tools for Automox MCP."""

from __future__ import annotations

import logging
import os
from typing import Any, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from .. import workflows
from ..client import AutomoxClient
from ..schemas import (
    InviteUserParams,
    ListOrgApiKeysParams,
    RemoveUserFromAccountParams,
    ZoneAssignment,
)
from ..utils.tooling import (
    call_tool_workflow,
    check_idempotency,
    maybe_format_markdown,
    store_idempotency,
)

logger = logging.getLogger(__name__)


def register(server: FastMCP, *, read_only: bool = False, client: AutomoxClient) -> None:
    """Register account-related tools."""

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

    if not read_only:

        @server.tool(
            name="invite_user_to_account",
            description="Invite a user to the Automox account with optional zone assignments.",
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": False,
                "openWorldHint": True,
            },
        )
        async def invite_user_to_account(
            email: str,
            account_rbac_role: Literal["global-admin", "no-global-access"],
            zone_assignments: list[ZoneAssignment] | None = None,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "invite_user_to_account")
            if cached is not None:
                return cached

            params = {
                "account_id": _resolve_account_id(None),
                "email": email,
                "account_rbac_role": account_rbac_role,
                "zone_assignments": zone_assignments,
            }
            result = await call_tool_workflow(
                client,
                workflows.invite_user_to_account,
                params,
                params_model=InviteUserParams,
            )
            await store_idempotency(request_id, "invite_user_to_account", result)
            return result

        @server.tool(
            name="remove_user_from_account",
            description="Remove a user from the Automox account by UUID.",
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": True,
                "openWorldHint": True,
            },
        )
        async def remove_user_from_account(
            user_id: str,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "remove_user_from_account")
            if cached is not None:
                return cached

            params = {
                "account_id": _resolve_account_id(None),
                "user_id": user_id,
            }
            result = await call_tool_workflow(
                client,
                workflows.remove_user_from_account,
                params,
                params_model=RemoveUserFromAccountParams,
            )
            await store_idempotency(request_id, "remove_user_from_account", result)
            return result

    @server.tool(
        name="list_org_api_keys",
        description=(
            "List API keys for the Automox organization. "
            "Returns key names and IDs only — secrets are never exposed."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def list_org_api_keys(
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        org_id = client.org_id
        if org_id is None:
            raise ToolError("org_id required - set AUTOMOX_ORG_ID or pass org_id explicitly.")
        result = await call_tool_workflow(
            client,
            workflows.list_org_api_keys,
            {"org_id": org_id},
            params_model=ListOrgApiKeysParams,
        )
        return maybe_format_markdown(result, output_format)


__all__ = ["register"]
