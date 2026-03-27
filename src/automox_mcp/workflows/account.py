"""Account workflows for Automox MCP."""

from __future__ import annotations

from collections.abc import Mapping
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

    invitation = await client.post(f"/accounts/{account_id}/invitations", json_data=body)

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

    await client.delete(f"/accounts/{account_id}/users/{user_id}")

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


async def list_org_api_keys(
    client: AutomoxClient,
    *,
    org_id: int,
) -> dict[str, Any]:
    """List API keys for the organization (names and IDs only, secrets redacted)."""
    results = await client.get(f"/orgs/{org_id}/api_keys")

    if not isinstance(results, list):
        results = []

    keys: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, Mapping):
            continue
        entry: dict[str, Any] = {
            "id": item.get("id"),
            "name": item.get("name"),
        }
        for optional in ("created_at", "expires_at", "last_used_at", "enabled"):
            val = item.get(optional)
            if val is not None:
                entry[optional] = val
        keys.append(entry)

    return {
        "data": {
            "total_keys": len(keys),
            "api_keys": keys,
        },
        "metadata": {
            "deprecated_endpoint": False,
        },
    }
