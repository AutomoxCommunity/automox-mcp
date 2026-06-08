"""Account/user management tools for Automox MCP."""

from __future__ import annotations

import os
from typing import Any, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from .. import workflows
from ..client import AutomoxClient
from ..schemas import (
    CreateGlobalApiKeyParams,
    CreateUserApiKeyParams,
    CreateZoneParams,
    DeleteGlobalApiKeyParams,
    DeleteUserApiKeyParams,
    GetAccountParams,
    GetAccountUserParams,
    GetUserApiKeyParams,
    GetUserParams,
    GetZoneParams,
    InviteUserParams,
    ListAccountRbacRolesParams,
    ListOrganizationsParams,
    ListOrgApiKeysParams,
    ListUserApiKeysParams,
    ListUsersParams,
    ListZonesForUserParams,
    ListZonesParams,
    ListZoneUsersParams,
    RemoveUserFromAccountParams,
    UpdateGlobalApiKeyParams,
    UpdateUserApiKeyParams,
    UpdateUserParams,
    ZoneAssignment,
)
from ..utils.tooling import (
    ToolReturn,
    call_tool_workflow,
    check_idempotency,
    maybe_format_markdown,
    release_idempotency,
    store_idempotency,
)


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
            "Returns key metadata (name, enabled, expiry) only — secrets are never exposed."
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
    ) -> ToolReturn:
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
            "List organizations visible to the API key, with device count, device "
            "limit, parent org, and trial end time. Useful for MSP/multi-org "
            "navigation, capacity posture, and trial warnings. A `tier` slug may be "
            "present per spec but has no defined feature ordering and is absent on some "
            "tenants — do not infer a paid-plan or capability ranking from it."
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
    ) -> ToolReturn:
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
    ) -> ToolReturn:
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
    ) -> ToolReturn:
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
    ) -> ToolReturn:
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
    ) -> ToolReturn:
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
            "role, verification, and 2FA type. two_factor_authentication "
            "carries the literal string 'disabled' when 2FA is OFF (do NOT "
            "read it as a configured type); a null/absent value is ambiguous "
            "(may mean disabled or not-reported) — see metadata.field_notes."
        ),
        annotations=_READ_ANNOTATIONS,
    )
    async def get_account_user(
        user_id: str,
        output_format: str | None = "json",
    ) -> ToolReturn:
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
    ) -> ToolReturn:
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
    ) -> ToolReturn:
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
    ) -> ToolReturn:
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
    ) -> ToolReturn:
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

    @server.tool(
        name="list_user_api_keys",
        description=(
            "List a user's API keys by user ID. Returns key metadata (name, "
            "enabled, expiry) only — secrets are never exposed."
        ),
        annotations=_READ_ANNOTATIONS,
    )
    async def list_user_api_keys(
        user_id: int,
        page: int | None = None,
        limit: int | None = None,
        output_format: str | None = "json",
    ) -> ToolReturn:
        result = await call_tool_workflow(
            client,
            workflows.list_user_api_keys,
            {"user_id": user_id, "page": page, "limit": limit},
            params_model=ListUserApiKeysParams,
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="get_user_api_key",
        description=(
            "Get one user API key by user ID and key ID. Returns metadata only "
            "— the secret is never exposed."
        ),
        annotations=_READ_ANNOTATIONS,
    )
    async def get_user_api_key(
        user_id: int,
        key_id: int,
        output_format: str | None = "json",
    ) -> ToolReturn:
        result = await call_tool_workflow(
            client,
            workflows.get_user_api_key,
            {"user_id": user_id, "key_id": key_id},
            params_model=GetUserApiKeyParams,
        )
        return maybe_format_markdown(result, output_format)

    @server.tool(
        name="list_global_api_keys",
        description=(
            "List global (account-scoped) API keys. Returns key metadata (name, "
            "enabled, expiry) only — secrets are never exposed."
        ),
        annotations=_READ_ANNOTATIONS,
    )
    async def list_global_api_keys(
        output_format: str | None = "json",
    ) -> ToolReturn:
        result = await call_tool_workflow(client, workflows.list_global_api_keys, {})
        return maybe_format_markdown(result, output_format)

    if not read_only:

        @server.tool(
            name="create_zone",
            description=(
                "Create a new zone (organization) in the account. "
                "The zone access_key is never surfaced."
            ),
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": False,
                "openWorldHint": True,
            },
        )
        async def create_zone(
            name: str,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "create_zone")
            if cached is not None:
                return cached
            try:
                result = await call_tool_workflow(
                    client,
                    workflows.create_zone,
                    {"account_id": _resolve_account_id(None), "name": name},
                    params_model=CreateZoneParams,
                )
            except BaseException:
                await release_idempotency(request_id, "create_zone")
                raise
            await store_idempotency(request_id, "create_zone", result)
            return result

        @server.tool(
            name="update_user",
            description=(
                "Update a user's profile fields (firstname, lastname, email, "
                "tfa_type) by user ID. Passwords cannot be set through this tool."
            ),
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": True,
                "openWorldHint": True,
            },
        )
        async def update_user(
            user_id: int,
            firstname: str | None = None,
            lastname: str | None = None,
            email: str | None = None,
            tfa_type: str | None = None,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "update_user")
            if cached is not None:
                return cached
            params: dict[str, Any] = {"user_id": user_id}
            for key, value in (
                ("firstname", firstname),
                ("lastname", lastname),
                ("email", email),
                ("tfa_type", tfa_type),
            ):
                if value is not None:
                    params[key] = value
            try:
                result = await call_tool_workflow(
                    client,
                    workflows.update_user,
                    params,
                    params_model=UpdateUserParams,
                )
            except BaseException:
                await release_idempotency(request_id, "update_user")
                raise
            await store_idempotency(request_id, "update_user", result)
            return result

        @server.tool(
            name="create_user_api_key",
            description=(
                "Create an API key for a user. Returns metadata only — the key "
                "secret is never surfaced and cannot be retrieved via MCP."
            ),
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": False,
                "openWorldHint": True,
            },
        )
        async def create_user_api_key(
            user_id: int,
            name: str,
            expires_at: str | None = None,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "create_user_api_key")
            if cached is not None:
                return cached
            params: dict[str, Any] = {"user_id": user_id, "name": name}
            if expires_at is not None:
                params["expires_at"] = expires_at
            try:
                result = await call_tool_workflow(
                    client,
                    workflows.create_user_api_key,
                    params,
                    params_model=CreateUserApiKeyParams,
                )
            except BaseException:
                await release_idempotency(request_id, "create_user_api_key")
                raise
            await store_idempotency(request_id, "create_user_api_key", result)
            return result

        @server.tool(
            name="update_user_api_key",
            description="Enable or disable a user API key by user ID and key ID.",
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": True,
                "openWorldHint": True,
            },
        )
        async def update_user_api_key(
            user_id: int,
            key_id: int,
            is_enabled: bool,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "update_user_api_key")
            if cached is not None:
                return cached
            try:
                result = await call_tool_workflow(
                    client,
                    workflows.update_user_api_key,
                    {"user_id": user_id, "key_id": key_id, "is_enabled": is_enabled},
                    params_model=UpdateUserApiKeyParams,
                )
            except BaseException:
                await release_idempotency(request_id, "update_user_api_key")
                raise
            await store_idempotency(request_id, "update_user_api_key", result)
            return result

        @server.tool(
            name="delete_user_api_key",
            description="Permanently delete a user API key by user ID and key ID.",
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": True,
                "openWorldHint": True,
            },
        )
        async def delete_user_api_key(
            user_id: int,
            key_id: int,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "delete_user_api_key")
            if cached is not None:
                return cached
            try:
                result = await call_tool_workflow(
                    client,
                    workflows.delete_user_api_key,
                    {"user_id": user_id, "key_id": key_id},
                    params_model=DeleteUserApiKeyParams,
                )
            except BaseException:
                await release_idempotency(request_id, "delete_user_api_key")
                raise
            await store_idempotency(request_id, "delete_user_api_key", result)
            return result

        @server.tool(
            name="create_global_api_key",
            description=(
                "Create a global (account-scoped) API key. Returns metadata only "
                "— the key secret is never surfaced and cannot be retrieved via MCP."
            ),
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": False,
                "openWorldHint": True,
            },
        )
        async def create_global_api_key(
            name: str,
            expires_at: str | None = None,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "create_global_api_key")
            if cached is not None:
                return cached
            params: dict[str, Any] = {"name": name}
            if expires_at is not None:
                params["expires_at"] = expires_at
            try:
                result = await call_tool_workflow(
                    client,
                    workflows.create_global_api_key,
                    params,
                    params_model=CreateGlobalApiKeyParams,
                )
            except BaseException:
                await release_idempotency(request_id, "create_global_api_key")
                raise
            await store_idempotency(request_id, "create_global_api_key", result)
            return result

        @server.tool(
            name="update_global_api_key",
            description="Enable or disable a global (account-scoped) API key by ID.",
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": True,
                "openWorldHint": True,
            },
        )
        async def update_global_api_key(
            key_id: int,
            is_enabled: bool,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "update_global_api_key")
            if cached is not None:
                return cached
            try:
                result = await call_tool_workflow(
                    client,
                    workflows.update_global_api_key,
                    {"key_id": key_id, "is_enabled": is_enabled},
                    params_model=UpdateGlobalApiKeyParams,
                )
            except BaseException:
                await release_idempotency(request_id, "update_global_api_key")
                raise
            await store_idempotency(request_id, "update_global_api_key", result)
            return result

        @server.tool(
            name="delete_global_api_key",
            description="Permanently delete a global (account-scoped) API key by ID.",
            annotations={
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": True,
                "openWorldHint": True,
            },
        )
        async def delete_global_api_key(
            key_id: int,
            request_id: str | None = None,
        ) -> dict[str, Any]:
            cached = await check_idempotency(request_id, "delete_global_api_key")
            if cached is not None:
                return cached
            try:
                result = await call_tool_workflow(
                    client,
                    workflows.delete_global_api_key,
                    {"key_id": key_id},
                    params_model=DeleteGlobalApiKeyParams,
                )
            except BaseException:
                await release_idempotency(request_id, "delete_global_api_key")
                raise
            await store_idempotency(request_id, "delete_global_api_key", result)
            return result


__all__ = ["register"]
