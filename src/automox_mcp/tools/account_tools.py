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
    GetAccountParams,
    GetAccountUserParams,
    GetUserParams,
    GetZoneParams,
    InviteUserParams,
    ListAccountRbacRolesParams,
    ListOrganizationsParams,
    ListOrgApiKeysParams,
    ListUsersParams,
    ListZonesForUserParams,
    ListZonesParams,
    ListZoneUsersParams,
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

    @server.tool(
        name="list_organizations",
        description=(
            "List organizations visible to the API key, with tier, device count, "
            "device limit, parent org, and trial end time. Useful for MSP/multi-org "
            "navigation, feature-tier checks, capacity posture, and trial warnings."
        ),
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def list_organizations(
        page: int | None = None,
        limit: int | None = None,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await call_tool_workflow(
            client,
            workflows.list_organizations,
            {"page": page, "limit": limit},
            params_model=ListOrganizationsParams,
        )
        return maybe_format_markdown(result, output_format)

    # ------------------------------------------------------------------
    # Identity inspection — read-only (issue #91 category A)
    # ------------------------------------------------------------------

    _READ_ANNOTATIONS = {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }

    @server.tool(
        name="list_users",
        description=(
            "List users in the organization with name, email, and RBAC roles. "
            "Secrets (e.g. intercom_hmac) are never surfaced."
        ),
        annotations=_READ_ANNOTATIONS,
    )
    async def list_users(
        page: int | None = None,
        limit: int | None = None,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await call_tool_workflow(
            client,
            workflows.list_users,
            {"page": page, "limit": limit},
            params_model=ListUsersParams,
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="get_user",
        description=(
            "Get a single user by numeric ID, including org/server-group "
            "membership and RBAC roles. Secrets are never surfaced."
        ),
        annotations=_READ_ANNOTATIONS,
    )
    async def get_user(
        user_id: int,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await call_tool_workflow(
            client,
            workflows.get_user,
            {"user_id": user_id},
            params_model=GetUserParams,
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="get_account",
        description="Get Automox account detail (id, name, type, timestamps).",
        annotations=_READ_ANNOTATIONS,
    )
    async def get_account(
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await call_tool_workflow(
            client,
            workflows.get_account,
            {"account_id": _resolve_account_id(None)},
            params_model=GetAccountParams,
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="list_account_rbac_roles",
        description="List the RBAC roles available in the Automox account.",
        annotations=_READ_ANNOTATIONS,
    )
    async def list_account_rbac_roles(
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await call_tool_workflow(
            client,
            workflows.list_account_rbac_roles,
            {"account_id": _resolve_account_id(None)},
            params_model=ListAccountRbacRolesParams,
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="get_account_user",
        description=(
            "Get an account-scoped user record by UUID: status, account RBAC "
            "role, verification, and 2FA state."
        ),
        annotations=_READ_ANNOTATIONS,
    )
    async def get_account_user(
        user_id: str,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await call_tool_workflow(
            client,
            workflows.get_account_user,
            {"account_id": _resolve_account_id(None), "user_id": user_id},
            params_model=GetAccountUserParams,
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="list_zones_for_user",
        description="List the zones (organizations) a given user belongs to.",
        annotations=_READ_ANNOTATIONS,
    )
    async def list_zones_for_user(
        user_id: str,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await call_tool_workflow(
            client,
            workflows.list_zones_for_user,
            {"account_id": _resolve_account_id(None), "user_id": user_id},
            params_model=ListZonesForUserParams,
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="list_zones",
        description="List the zones (organizations) in the Automox account.",
        annotations=_READ_ANNOTATIONS,
    )
    async def list_zones(
        page: int | None = None,
        limit: int | None = None,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await call_tool_workflow(
            client,
            workflows.list_zones,
            {"account_id": _resolve_account_id(None), "page": page, "limit": limit},
            params_model=ListZonesParams,
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="get_zone",
        description=(
            "Get a single zone (organization) by UUID. The zone access_key is never surfaced."
        ),
        annotations=_READ_ANNOTATIONS,
    )
    async def get_zone(
        zone_id: str,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await call_tool_workflow(
            client,
            workflows.get_zone,
            {"account_id": _resolve_account_id(None), "zone_id": zone_id},
            params_model=GetZoneParams,
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="list_zone_users",
        description="List the users assigned to a given zone (by zone UUID).",
        annotations=_READ_ANNOTATIONS,
    )
    async def list_zone_users(
        zone_id: str,
        page: int | None = None,
        limit: int | None = None,
        output_format: str | None = "json",
    ) -> dict[str, Any]:
        result = await call_tool_workflow(
            client,
            workflows.list_zone_users,
            {
                "account_id": _resolve_account_id(None),
                "zone_id": zone_id,
                "page": page,
                "limit": limit,
            },
            params_model=ListZoneUsersParams,
        )
        return maybe_format_markdown(result, output_format)


__all__ = ["register"]
