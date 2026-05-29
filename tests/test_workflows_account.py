"""Tests for automox_mcp.workflows.account."""

from __future__ import annotations

from typing import cast

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.account import (
    get_account,
    get_account_user,
    get_user,
    get_zone,
    invite_user_to_account,
    list_account_rbac_roles,
    list_org_api_keys,
    list_organizations,
    list_users,
    list_zone_users,
    list_zones,
    list_zones_for_user,
    remove_user_from_account,
)

ACCOUNT_ID = "acct-uuid-1234"
USER_ID = "user-uuid-5678"


@pytest.mark.asyncio
async def test_invite_user_returns_email_and_role():
    invitation_response = {"id": "invite-abc", "status": "pending"}
    client = StubClient(post_responses={"/accounts/": [invitation_response]})
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
    client = StubClient(post_responses={"/accounts/": [{"id": "invite-xyz"}]})
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
    client = StubClient(delete_responses={"/accounts/": [{}]})
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


# ---------------------------------------------------------------------------
# list_org_api_keys
# ---------------------------------------------------------------------------

_API_KEYS = [
    {
        "id": 1,
        "name": "CI Key",
        "created_at": "2026-01-01T00:00:00Z",
        "enabled": True,
    },
    {
        "id": 2,
        "name": "Dev Key",
        "expires_at": "2027-01-01T00:00:00Z",
    },
]


@pytest.mark.asyncio
async def test_list_api_keys_returns_summary():
    client = StubClient(get_responses={"/orgs/42/api_keys": [_API_KEYS]})
    result = await list_org_api_keys(cast(AutomoxClient, client), org_id=42)

    assert result["data"]["total_keys"] == 2
    assert len(result["data"]["api_keys"]) == 2


@pytest.mark.asyncio
async def test_list_api_keys_includes_optional_fields():
    client = StubClient(get_responses={"/orgs/42/api_keys": [_API_KEYS]})
    result = await list_org_api_keys(cast(AutomoxClient, client), org_id=42)

    ci = next(k for k in result["data"]["api_keys"] if k["name"] == "CI Key")
    assert ci["enabled"] is True
    assert ci["created_at"] == "2026-01-01T00:00:00Z"

    dev = next(k for k in result["data"]["api_keys"] if k["name"] == "Dev Key")
    assert dev["expires_at"] == "2027-01-01T00:00:00Z"
    assert "enabled" not in dev


@pytest.mark.asyncio
async def test_list_api_keys_handles_empty():
    client = StubClient(get_responses={"/orgs/42/api_keys": [[]]})
    result = await list_org_api_keys(cast(AutomoxClient, client), org_id=42)
    assert result["data"]["total_keys"] == 0


@pytest.mark.asyncio
async def test_list_api_keys_handles_non_list():
    client = StubClient(get_responses={"/orgs/42/api_keys": ["unexpected"]})
    result = await list_org_api_keys(cast(AutomoxClient, client), org_id=42)
    assert result["data"]["total_keys"] == 0


# ---------------------------------------------------------------------------
# list_organizations (issue #91 category H)
# ---------------------------------------------------------------------------


_ORGS = [
    {
        "id": 42,
        "uuid": "org-uuid-42",
        "name": "Acme Prod",
        "tier": "enterprise",
        "device_count": 1200,
        "device_limit": 2000,
        "soft_device_limit": 1800,
        "parent_id": None,
        "trial_end_time": None,
        "create_time": "2024-01-01T00:00:00Z",
        "access_key": "should-not-be-surfaced",
    },
    {
        "id": 43,
        "uuid": "org-uuid-43",
        "name": "Acme Child",
        "tier": "patch",
        "device_count": 50,
        "parent_id": 42,
    },
]


@pytest.mark.asyncio
async def test_list_organizations_projects_expected_fields():
    client = StubClient(get_responses={"/orgs": [_ORGS]})
    result = await list_organizations(cast(AutomoxClient, client))

    data = result["data"]
    assert data["total_organizations"] == 2

    parent = next(o for o in data["organizations"] if o["id"] == 42)
    assert parent["tier"] == "enterprise"
    assert parent["device_count"] == 1200
    assert parent["device_limit"] == 2000
    # access_key is not part of the projection -> never surfaced
    assert "access_key" not in parent

    child = next(o for o in data["organizations"] if o["id"] == 43)
    assert child["parent_id"] == 42
    # None-valued fields are omitted, not echoed as null
    assert "trial_end_time" not in child


@pytest.mark.asyncio
async def test_list_organizations_forwards_pagination():
    client = StubClient(get_responses={"/orgs": [_ORGS]})
    await list_organizations(cast(AutomoxClient, client), page=1, limit=50)
    _, path, params = client.calls[0]
    assert path == "/orgs"
    assert params == {"page": 1, "limit": 50}


@pytest.mark.asyncio
async def test_list_organizations_handles_non_list():
    client = StubClient(get_responses={"/orgs": ["unexpected"]})
    result = await list_organizations(cast(AutomoxClient, client))
    assert result["data"]["total_organizations"] == 0


# ---------------------------------------------------------------------------
# Identity inspection — read-only (issue #91 category A)
# ---------------------------------------------------------------------------

_ACCT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_USER_RECORD = {
    "id": 7,
    "firstname": "Ada",
    "lastname": "Lovelace",
    "email": "ada@example.com",
    "account_id": 42,
    "account_name": "Acme",
    "account_rbac_roles": ["global-admin"],
    "rbac_roles": ["admin"],
    "tfa_type": "totp",
    "orgs": [42, 43],
    "server_groups": [1, 2],
    "intercom_hmac": "SECRET-HMAC-DO-NOT-LEAK",
    "prefs": {"theme": "dark"},
}


@pytest.mark.asyncio
async def test_list_users_projects_and_redacts_secret():
    client = StubClient(get_responses={"/users": [[_USER_RECORD]]})
    result = await list_users(cast(AutomoxClient, client), org_id=42)

    assert result["data"]["total_users"] == 1
    user = result["data"]["users"][0]
    assert user["email"] == "ada@example.com"
    assert user["rbac_roles"] == ["admin"]
    # secret + noise never surfaced; list view stays lean
    assert "intercom_hmac" not in user
    assert "prefs" not in user
    assert "orgs" not in user  # lean list projection

    _, path, params = client.calls[0]
    assert path == "/users"
    assert params["o"] == 42


@pytest.mark.asyncio
async def test_get_user_detail_projection_redacts_secret():
    client = StubClient(get_responses={"/users/7": [_USER_RECORD]})
    result = await get_user(cast(AutomoxClient, client), org_id=42, user_id=7)
    data = result["data"]
    assert data["email"] == "ada@example.com"
    assert data["orgs"] == [42, 43]  # detail view includes membership
    assert "intercom_hmac" not in data
    _, _path, params = client.calls[0]
    assert params == {"o": 42}


@pytest.mark.asyncio
async def test_get_account_passthrough():
    account = {"id": 1, "name": "Acme", "type": "msp", "created_at": "2024-01-01T00:00:00Z"}
    client = StubClient(get_responses={f"/accounts/{_ACCT}": [account]})
    result = await get_account(cast(AutomoxClient, client), account_id=_ACCT)
    assert result["data"]["name"] == "Acme"
    assert result["metadata"]["account_id"] == _ACCT


@pytest.mark.asyncio
async def test_list_account_rbac_roles_unwraps_envelope():
    envelope = {"metadata": {"total": 2}, "data": [{"name": "global-admin"}, {"name": "read-only"}]}
    client = StubClient(get_responses={f"/accounts/{_ACCT}/rbac-roles": [envelope]})
    result = await list_account_rbac_roles(cast(AutomoxClient, client), account_id=_ACCT)
    assert result["data"]["total_roles"] == 2
    assert result["data"]["rbac_roles"][0]["name"] == "global-admin"


@pytest.mark.asyncio
async def test_get_account_user_passthrough():
    user = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    record = {"user_id": user, "email": "x@y.z", "status": "active", "account_rbac_role": "admin"}
    client = StubClient(get_responses={f"/accounts/{_ACCT}/users/{user}": [record]})
    result = await get_account_user(cast(AutomoxClient, client), account_id=_ACCT, user_id=user)
    assert result["data"]["status"] == "active"


@pytest.mark.asyncio
async def test_list_zones_for_user_unwraps_envelope():
    user = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    envelope = {"data": [{"id": "z1"}, {"id": "z2"}], "metadata": {}}
    client = StubClient(get_responses={f"/accounts/{_ACCT}/users/{user}/zones": [envelope]})
    result = await list_zones_for_user(cast(AutomoxClient, client), account_id=_ACCT, user_id=user)
    assert result["data"]["total_zones"] == 2
    assert result["data"]["user_id"] == user


@pytest.mark.asyncio
async def test_list_zones_forwards_pagination():
    envelope = {"data": [{"id": "z1"}], "metadata": {}}
    client = StubClient(get_responses={f"/accounts/{_ACCT}/zones": [envelope]})
    await list_zones(cast(AutomoxClient, client), account_id=_ACCT, page=1, limit=25)
    _, _path, params = client.calls[0]
    assert params == {"page": 1, "limit": 25}


@pytest.mark.asyncio
async def test_get_zone_redacts_access_key():
    zone = {
        "id": "z1",
        "organization_id": 99,
        "account_id": 1,
        "name": "EU Zone",
        "access_key": "SECRET-ZONE-KEY",
    }
    zid = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    client = StubClient(get_responses={f"/accounts/{_ACCT}/zones/{zid}": [zone]})
    result = await get_zone(cast(AutomoxClient, client), account_id=_ACCT, zone_id=zid)
    assert result["data"]["name"] == "EU Zone"
    assert "access_key" not in result["data"]


@pytest.mark.asyncio
async def test_list_zone_users_unwraps_envelope():
    zid = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    envelope = {"data": [{"user_id": "u1"}], "metadata": {}}
    client = StubClient(get_responses={f"/accounts/{_ACCT}/zones/{zid}/users": [envelope]})
    result = await list_zone_users(cast(AutomoxClient, client), account_id=_ACCT, zone_id=zid)
    assert result["data"]["total_users"] == 1
    assert result["data"]["zone_id"] == zid
