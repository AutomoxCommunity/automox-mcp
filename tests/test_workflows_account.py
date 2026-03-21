"""Tests for automox_mcp.workflows.account."""

from __future__ import annotations

from typing import cast

import pytest

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.account import (
    invite_user_to_account,
    remove_user_from_account,
)


class StubClient:
    def __init__(
        self,
        *,
        get_responses=None,
        post_responses=None,
        delete_responses=None,
        org_id=42,
        org_uuid=None,
        account_uuid="test-account",
    ):
        self.org_id = org_id
        self.org_uuid = org_uuid
        self.account_uuid = account_uuid
        self._get = get_responses or {}
        self._post = post_responses or {}
        self._delete = delete_responses or {}

    async def get(self, path, *, params=None, headers=None):
        for prefix, responses in self._get.items():
            if path.startswith(prefix) and responses:
                return responses.pop(0)
        return {}

    async def post(self, path, *, json_data=None, params=None, headers=None):
        for prefix, responses in self._post.items():
            if path.startswith(prefix) and responses:
                return responses.pop(0)
        return {}

    async def delete(self, path, *, params=None, headers=None):
        for prefix, responses in self._delete.items():
            if path.startswith(prefix) and responses:
                return responses.pop(0)
        return {}


ACCOUNT_ID = "acct-uuid-1234"
USER_ID = "user-uuid-5678"


@pytest.mark.asyncio
async def test_invite_user_returns_email_and_role():
    invitation_response = {"id": "invite-abc", "status": "pending"}
    client = StubClient(
        post_responses={"/accounts/": [invitation_response]}
    )
    result = await invite_user_to_account(
        cast(AutomoxClient, client),
        account_id=ACCOUNT_ID,
        email="newuser@example.com",
        account_rbac_role="Administrator",
    )

    data = result["data"]
    assert data["email"] == "newuser@example.com"
    assert data["account_rbac_role"] == "Administrator"
    assert data["zone_assignments"] is None
    assert data["invitation"] == invitation_response

    meta = result["metadata"]
    assert meta["account_id"] == ACCOUNT_ID
    assert meta["deprecated_endpoint"] is False


@pytest.mark.asyncio
async def test_invite_user_with_zone_assignments():
    zones = [{"zone_id": "zone-1", "role": "ReadOnly"}]
    client = StubClient(
        post_responses={"/accounts/": [{"id": "invite-xyz"}]}
    )
    result = await invite_user_to_account(
        cast(AutomoxClient, client),
        account_id=ACCOUNT_ID,
        email="zoneuser@example.com",
        account_rbac_role="ReadOnly",
        zone_assignments=zones,
    )

    assert result["data"]["zone_assignments"] == zones


@pytest.mark.asyncio
async def test_remove_user_returns_user_id_and_removed_true():
    client = StubClient(
        delete_responses={"/accounts/": [{}]}
    )
    result = await remove_user_from_account(
        cast(AutomoxClient, client),
        account_id=ACCOUNT_ID,
        user_id=USER_ID,
    )

    data = result["data"]
    assert data["user_id"] == USER_ID
    assert data["removed"] is True

    meta = result["metadata"]
    assert meta["account_id"] == ACCOUNT_ID
    assert meta["deprecated_endpoint"] is False


@pytest.mark.asyncio
async def test_remove_user_with_uuid_objects():
    from uuid import UUID

    acct_uuid = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    user_uuid = UUID("11111111-2222-3333-4444-555555555555")

    client = StubClient(delete_responses={"/accounts/": [{}]})
    result = await remove_user_from_account(
        cast(AutomoxClient, client),
        account_id=acct_uuid,
        user_id=user_uuid,
    )

    assert result["data"]["user_id"] == str(user_uuid)
    assert result["metadata"]["account_id"] == str(acct_uuid)
