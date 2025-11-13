"""Account workflows for Automox MCP."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from ..client import AutomoxClient


async def invite_user_to_account(
    client: AutomoxClient,
    *,
    account_id: str | UUID,
    email: str,
    account_rbac_role: str,
    zone_assignments: list | None = None,
) -> dict[str, Any]:
    """Invite a user to an Automox account with optional zone assignments."""

    body: dict[str, Any] = {
        "email": email,
        "account_rbac_role": account_rbac_role,
    }
    if zone_assignments is not None:
        body["zone_assignments"] = zone_assignments

    invitation = await client.post(
        f"/accounts/{account_id}/invitations", json_data=body, api="console"
    )

    data = {
        "email": email,
        "account_rbac_role": account_rbac_role,
        "zone_assignments": zone_assignments,
        "invitation": invitation,
    }

    metadata = {
        "deprecated_endpoint": False,
        "account_id": str(account_id),
    }

    return {
        "data": data,
        "metadata": metadata,
    }


async def remove_user_from_account(
    client: AutomoxClient,
    *,
    account_id: str | UUID,
    user_id: str | UUID,
) -> dict[str, Any]:
    """Remove an Automox user from the account."""

    await client.delete(f"/accounts/{account_id}/users/{user_id}", api="console")

    data = {
        "user_id": str(user_id),
        "removed": True,
    }

    metadata = {
        "deprecated_endpoint": False,
        "account_id": str(account_id),
    }

    return {
        "data": data,
        "metadata": metadata,
    }
