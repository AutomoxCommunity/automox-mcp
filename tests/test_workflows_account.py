"""Tests for automox_mcp.workflows.account."""

from __future__ import annotations

from typing import cast

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.account import (
    create_global_api_key,
    create_user_api_key,
    create_zone,
    delete_global_api_key,
    delete_user_api_key,
    get_account,
    get_account_user,
    get_user,
    get_user_api_key,
    get_zone,
    invite_user_to_account,
    list_account_rbac_roles,
    list_global_api_keys,
    list_org_api_keys,
    list_organizations,
    list_user_api_keys,
    list_users,
    list_zone_users,
    list_zones,
    list_zones_for_user,
    remove_user_from_account,
    update_global_api_key,
    update_user,
    update_user_api_key,
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

# Captured (sanitized) shape of GET /orgs/{id}/api_keys, probed live
# 2026-06-05: a {"results": [...], "size": N} envelope (NOT a bare list), with
# each item keyed id/name/created_at/expires_at/is_enabled/user. The prior
# fixture was an invented bare list with an `enabled` key the API never returns
# — the #132 "stub from the code's own wrong mental model" trap that let the
# envelope-drop bug pass CI while the live tool returned zero keys. Identifiers,
# the embedded user blob, and timestamps are sanitized.
_API_KEYS_ENVELOPE = {
    "results": [
        {
            "id": 1001,
            "name": "ci-automation",
            "created_at": "2026-01-01T00:00:00Z",
            "expires_at": None,
            "is_enabled": True,
            "user": {
                "id": 5001,
                "email": "redacted@example.com",
                "firstname": "Red",
                "lastname": "Acted",
            },
        },
        {
            "id": 1002,
            "name": "dev-readonly",
            "created_at": "2026-02-01T00:00:00Z",
            "expires_at": "2027-01-01T00:00:00Z",
            "is_enabled": False,
            "user": {
                "id": 5002,
                "email": "redacted2@example.com",
                "firstname": "Also",
                "lastname": "Redacted",
            },
        },
    ],
    "size": 2,
}


@pytest.mark.asyncio
async def test_list_api_keys_unwraps_envelope():
    """Reconciles to the envelope size, not zero (the N1 regression witness)."""
    client = StubClient(get_responses={"/orgs/42/api_keys": [_API_KEYS_ENVELOPE]})
    result = await list_org_api_keys(cast(AutomoxClient, client), org_id=42)

    assert result["data"]["total_keys"] == 2
    assert len(result["data"]["api_keys"]) == 2
    # Envelope size surfaced for count==size reconciliation.
    assert result["metadata"]["total_size"] == 2


@pytest.mark.asyncio
async def test_list_api_keys_projects_real_fields():
    client = StubClient(get_responses={"/orgs/42/api_keys": [_API_KEYS_ENVELOPE]})
    result = await list_org_api_keys(cast(AutomoxClient, client), org_id=42)

    ci = next(k for k in result["data"]["api_keys"] if k["name"] == "ci-automation")
    # Live DTO key is `is_enabled`, not the previously-read phantom `enabled`.
    assert ci["is_enabled"] is True
    assert "enabled" not in ci
    assert ci["created_at"] == "2026-01-01T00:00:00Z"

    dev = next(k for k in result["data"]["api_keys"] if k["name"] == "dev-readonly")
    assert dev["expires_at"] == "2027-01-01T00:00:00Z"
    # is_enabled=False is a real value and must be surfaced (not dropped as falsy
    # the way the projection drops None-valued optionals).
    assert dev["is_enabled"] is False

    # The embedded user blob (email/name PII) is never forwarded.
    for key in result["data"]["api_keys"]:
        assert "user" not in key


@pytest.mark.asyncio
async def test_list_api_keys_handles_empty_envelope():
    client = StubClient(get_responses={"/orgs/42/api_keys": [{"results": [], "size": 0}]})
    result = await list_org_api_keys(cast(AutomoxClient, client), org_id=42)
    assert result["data"]["total_keys"] == 0
    assert result["metadata"]["total_size"] == 0


@pytest.mark.asyncio
async def test_list_api_keys_handles_bare_list_fallback():
    """Defensive parity: a bare list (no envelope) still projects."""
    client = StubClient(
        get_responses={"/orgs/42/api_keys": [[{"id": 1, "name": "legacy", "is_enabled": True}]]}
    )
    result = await list_org_api_keys(cast(AutomoxClient, client), org_id=42)
    assert result["data"]["total_keys"] == 1
    # No envelope => no size to reconcile.
    assert "total_size" not in result["metadata"]


@pytest.mark.asyncio
async def test_list_api_keys_handles_non_list():
    client = StubClient(get_responses={"/orgs/42/api_keys": ["unexpected"]})
    result = await list_org_api_keys(cast(AutomoxClient, client), org_id=42)
    assert result["data"]["total_keys"] == 0


# ---------------------------------------------------------------------------
# list_organizations (issue #91 category H)
# ---------------------------------------------------------------------------


# Org 42 includes a spec `tier` slug (present on some tenants). Org 43 mirrors
# the LIVE GET /orgs key set on the probed tenant (2026-06-05): NO `tier` field
# at all — keys observed were id, uuid, name, device_count, soft_device_limit,
# create_time. The projection drops absent keys, so tier must simply not appear.
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
    },
    {
        "id": 43,
        "uuid": "org-uuid-43",
        "name": "Acme Child",
        "device_count": 50,
        "soft_device_limit": 100,
        "create_time": "2024-02-01T00:00:00Z",
    },
]


@pytest.mark.asyncio
async def test_list_organizations_projects_expected_fields():
    client = StubClient(get_responses={"/orgs": [_ORGS]})
    result = await list_organizations(cast(AutomoxClient, client))

    data = result["data"]
    assert data["organizations_returned"] == 2

    # (a) tier forwarded when present in the input item.
    parent = next(o for o in data["organizations"] if o["id"] == 42)
    assert parent["tier"] == "enterprise"
    assert parent["device_count"] == 1200
    assert parent["device_limit"] == 2000

    # (b) tier omitted (no error) when absent — the live-tenant case from the
    # probe, where GET /orgs returns no tier field at all.
    child = next(o for o in data["organizations"] if o["id"] == 43)
    assert "tier" not in child
    assert child["device_count"] == 50
    # None-valued / absent fields are omitted, not echoed as null.
    assert "trial_end_time" not in child
    assert "parent_id" not in child


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
    assert result["data"]["organizations_returned"] == 0


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
    # orgs[] is a list of org objects (each can carry a per-org access_key
    # secret upstream); the detail projection re-projects each through
    # _USER_ORG_FIELDS to strip access_key/saml/metadata.
    "orgs": [
        {"id": 42, "name": "Acme Prod", "access_key": "SECRET-ORG-KEY-DO-NOT-LEAK"},
        {"id": 43, "name": "Acme Child", "saml": {"idp": "x"}, "metadata": {"k": "v"}},
    ],
    "server_groups": [1, 2],
    "intercom_hmac": "SECRET-HMAC-DO-NOT-LEAK",
    "prefs": {"theme": "dark"},
}


@pytest.mark.asyncio
async def test_list_users_projects_and_redacts_secret():
    client = StubClient(get_responses={"/users": [[_USER_RECORD]]})
    result = await list_users(cast(AutomoxClient, client), org_id=42)

    assert result["data"]["users_returned"] == 1
    # Deprecated alias retained for the typed structured-output model.
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
    # detail view includes membership, re-projected to strip per-org secrets
    assert data["orgs"] == [
        {"id": 42, "name": "Acme Prod"},
        {"id": 43, "name": "Acme Child"},
    ]
    # No per-org access_key / saml / metadata is ever forwarded (N3 redaction).
    import json as _json

    blob = _json.dumps(data)
    assert "access_key" not in blob
    assert "SECRET-ORG-KEY-DO-NOT-LEAK" not in blob
    assert "intercom_hmac" not in data
    _, _path, params = client.calls[0]
    assert params == {"o": 42}


@pytest.mark.asyncio
async def test_get_user_carries_plan_legend_and_projects_orgs():
    # Spec-shaped orgs blob: per spec each org may carry a `plan` slug
    # (basic/manage/tier3). Live capture blocked — orgs[].plan was absent on the
    # probed tenant (2026-06-05) — so this fixture is spec-shaped, not captured.
    # access_key here proves the projection strips the secret while keeping plan.
    record = {
        "id": 7,
        "firstname": "Ada",
        "email": "ada@example.com",
        "orgs": [
            {"id": 42, "plan": "basic", "access_key": "LEAK"},
            {"id": 43, "plan": "manage"},
        ],
    }
    client = StubClient(get_responses={"/users/7": [record]})
    result = await get_user(cast(AutomoxClient, client), org_id=42, user_id=7)

    # plan is preserved (so the legend below is meaningful); access_key stripped.
    assert result["data"]["orgs"] == [
        {"id": 42, "plan": "basic"},
        {"id": 43, "plan": "manage"},
    ]
    # Legend present, attributing the vocabulary to spec (not asserting live).
    note = result["metadata"]["field_notes"]["orgs[].plan"]
    assert "plan" in note.lower()
    assert "spec" in note.lower()


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
    # Spec-shaped AccountUser fixture: live capture blocked (the /users probe
    # returned a generic API error on this key, 2026-06-05), so the 2FA field is
    # spec-shaped (anyOf[enum['email','google'], null]), not captured.
    record = {
        "user_id": user,
        "email": "x@y.z",
        "status": "active",
        "account_rbac_role": "admin",
        "two_factor_authentication": "email",
    }
    client = StubClient(get_responses={f"/accounts/{_ACCT}/users/{user}": [record]})
    result = await get_account_user(cast(AutomoxClient, client), account_id=_ACCT, user_id=user)
    assert result["data"]["status"] == "active"
    # Raw 2FA value forwarded unchanged.
    assert result["data"]["two_factor_authentication"] == "email"
    # Legend covers both the live 'disabled'=off case and the null ambiguity.
    note = result["metadata"]["field_notes"]["two_factor_authentication"]
    assert "ambiguous" in note.lower()
    assert "disabled" in note.lower()


@pytest.mark.asyncio
async def test_get_account_user_disabled_tfa_legend_says_off():
    # Live-observed (re-audit 2026-06-05): when 2FA is off the field carries the
    # literal string 'disabled', NOT null. The legend must tell the model this
    # means OFF, not a configured 2FA type.
    user = "dddddddd-dddd-dddd-dddd-dddddddddddd"
    record = {"user_id": user, "status": "active", "two_factor_authentication": "disabled"}
    client = StubClient(get_responses={f"/accounts/{_ACCT}/users/{user}": [record]})
    result = await get_account_user(cast(AutomoxClient, client), account_id=_ACCT, user_id=user)
    assert result["data"]["two_factor_authentication"] == "disabled"
    note = result["metadata"]["field_notes"]["two_factor_authentication"].lower()
    # The note must distinguish 'disabled'=OFF from a configured type.
    assert "'disabled' means 2fa is off" in note
    assert "live-verified" in note


@pytest.mark.asyncio
async def test_get_account_user_forwards_null_tfa_and_legend():
    user = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    # Spec-shaped: two_factor_authentication may be null (the ambiguous case).
    record = {"user_id": user, "status": "active", "two_factor_authentication": None}
    client = StubClient(get_responses={f"/accounts/{_ACCT}/users/{user}": [record]})
    result = await get_account_user(cast(AutomoxClient, client), account_id=_ACCT, user_id=user)
    # null forwarded verbatim, not coerced.
    assert result["data"]["two_factor_authentication"] is None
    assert "two_factor_authentication" in result["metadata"]["field_notes"]


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


@pytest.mark.asyncio
async def test_list_zone_users_projects_and_redacts_secret():
    """The zone-users endpoint returns the same User DTO that carries
    intercom_hmac; list_zone_users must project it out (it previously forwarded
    the raw DTO, with no downstream redaction for intercom_hmac). Identity, RBAC
    roles, and a uuid (if present) survive the allowlist projection."""
    zid = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    raw_user = {
        "id": 7,
        "uuid": "11111111-2222-3333-4444-555555555555",
        "firstname": "Ada",
        "lastname": "Lovelace",
        "email": "ada@example.com",
        "rbac_roles": ["admin"],
        "intercom_hmac": "SECRET-HMAC-DO-NOT-LEAK",
        "prefs": {"theme": "dark"},
    }
    envelope = {"data": [raw_user], "metadata": {}}
    client = StubClient(get_responses={f"/accounts/{_ACCT}/zones/{zid}/users": [envelope]})
    result = await list_zone_users(cast(AutomoxClient, client), account_id=_ACCT, zone_id=zid)

    user = result["data"]["users"][0]
    assert "intercom_hmac" not in user
    assert "SECRET-HMAC-DO-NOT-LEAK" not in str(result["data"])
    assert user["email"] == "ada@example.com"
    assert user["rbac_roles"] == ["admin"]
    # uuid preserved if the endpoint emits one (the account-user UUID, issue #193).
    assert user["uuid"] == "11111111-2222-3333-4444-555555555555"
    assert "prefs" not in user  # noise dropped by the deny-by-default allowlist


# ---------------------------------------------------------------------------
# Identity / zone / key writes (issue #91 category A, write slice)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_zone_redacts_access_key():
    zone = {"id": "z9", "organization_id": 5, "name": "EU", "access_key": "SECRET"}
    client = StubClient(post_responses={f"/accounts/{_ACCT}/zones": [zone]})
    result = await create_zone(cast(AutomoxClient, client), account_id=_ACCT, name="EU")
    assert result["data"]["name"] == "EU"
    assert result["data"]["created"] is True
    assert "access_key" not in result["data"]
    # conftest StubClient records POST as (method, path, json_data)
    _, path, body = client.calls[0]
    assert path == f"/accounts/{_ACCT}/zones"
    assert body == {"name": "EU"}


@pytest.mark.asyncio
async def test_update_user_builds_partial_body_no_password():
    client = StubClient(patch_responses={"/users/7": [{}]})
    result = await update_user(
        cast(AutomoxClient, client), user_id=7, email="a@b.c", firstname="Ada"
    )
    assert result["data"]["updated"] is True
    assert result["data"]["fields_updated"] == ["email", "firstname"]
    method, path, body = client.calls[0]
    assert method == "PATCH"
    assert path == "/users/7"
    assert body == {"email": "a@b.c", "firstname": "Ada"}
    assert "password" not in body


def test_update_user_params_requires_a_field():
    from pydantic import ValidationError

    from automox_mcp.schemas import UpdateUserParams

    with pytest.raises(ValidationError, match="at least one"):
        UpdateUserParams(user_id=7)


def test_update_user_params_forbids_password():
    from pydantic import ValidationError

    from automox_mcp.schemas import UpdateUserParams

    # password is not a declared field -> ForbidExtraModel rejects it
    with pytest.raises(ValidationError):
        UpdateUserParams(user_id=7, password="hunter2")


@pytest.mark.asyncio
async def test_list_user_api_keys_projects_metadata():
    payload = {
        "size": 1,
        "results": [
            {
                "id": 3,
                "name": "CI",
                "is_enabled": True,
                "expires_at": None,
                "created_at": "2026-01-01T00:00:00Z",
                "user": {"id": 7, "email": "a@b.c"},
            }
        ],
    }
    client = StubClient(get_responses={"/users/7/api_keys": [payload]})
    result = await list_user_api_keys(cast(AutomoxClient, client), org_id=42, user_id=7)
    assert result["data"]["keys_returned"] == 1
    # Envelope `size` is the real grand total, surfaced as total_keys.
    assert result["data"]["total_keys"] == 1
    key = result["data"]["api_keys"][0]
    assert key["name"] == "CI"
    assert "user" not in key  # lean projection drops the nested user blob
    _, _path, params = client.calls[0]
    assert params["o"] == 42


@pytest.mark.asyncio
async def test_get_user_api_key_metadata_only():
    rec = {"id": 3, "name": "CI", "is_enabled": True, "user": {"id": 7}}
    client = StubClient(get_responses={"/users/7/api_keys/3": [rec]})
    result = await get_user_api_key(cast(AutomoxClient, client), org_id=42, user_id=7, key_id=3)
    assert result["data"]["name"] == "CI"
    assert "user" not in result["data"]


@pytest.mark.asyncio
async def test_create_user_api_key_returns_metadata_no_secret():
    created = {"id": 9, "name": "new", "is_enabled": True, "api_key": "SHOULD-NOT-APPEAR"}
    client = StubClient(post_responses={"/users/7/api_keys": [created]})
    result = await create_user_api_key(
        cast(AutomoxClient, client), org_id=42, user_id=7, name="new", expires_at="2027-01-01"
    )
    assert result["data"]["id"] == 9
    assert result["data"]["created"] is True
    # secret is never surfaced even if the API echoes one
    assert "api_key" not in result["data"]
    assert "not be retrieved" in result["metadata"]["note"]
    _, path, body = client.calls[0]
    assert path == "/users/7/api_keys"
    assert body == {"name": "new", "expires_at": "2027-01-01"}


@pytest.mark.asyncio
async def test_update_user_api_key_toggles_enabled():
    rec = {"id": 3, "name": "CI", "is_enabled": False}
    client = StubClient(put_responses={"/users/7/api_keys/3": [rec]})
    result = await update_user_api_key(
        cast(AutomoxClient, client), org_id=42, user_id=7, key_id=3, is_enabled=False
    )
    assert result["data"]["updated"] is True
    assert result["data"]["is_enabled"] is False
    _, _path, body = client.calls[0]
    assert body == {"is_enabled": False}


@pytest.mark.asyncio
async def test_delete_user_api_key():
    client = StubClient(delete_responses={"/users/7/api_keys/3": [None]})
    result = await delete_user_api_key(cast(AutomoxClient, client), org_id=42, user_id=7, key_id=3)
    assert result["data"]["deleted"] is True
    assert result["data"]["key_id"] == 3
    # DELETE records params in the conftest stub -> verify org scoping
    _, _path, params = client.calls[0]
    assert params == {"o": 42}


@pytest.mark.asyncio
async def test_list_user_api_keys_pagination_and_non_mapping():
    # forwards page/limit; tolerates a non-mapping/non-list response
    client = StubClient(get_responses={"/users/7/api_keys": ["unexpected"]})
    result = await list_user_api_keys(
        cast(AutomoxClient, client), org_id=42, user_id=7, page=1, limit=5
    )
    assert result["data"]["keys_returned"] == 0
    # No envelope size => no real total surfaced.
    assert "total_keys" not in result["data"]
    _, _path, params = client.calls[0]
    assert params == {"o": 42, "page": 1, "limit": 5}


@pytest.mark.asyncio
async def test_list_account_rbac_roles_accepts_bare_list():
    # _envelope plain-list branch (no {data,metadata} wrapper)
    client = StubClient(get_responses={f"/accounts/{_ACCT}/rbac-roles": [[{"name": "admin"}]]})
    result = await list_account_rbac_roles(cast(AutomoxClient, client), account_id=_ACCT)
    assert result["data"]["total_roles"] == 1


@pytest.mark.asyncio
async def test_create_user_api_key_without_expiry_and_non_mapping():
    client = StubClient(post_responses={"/users/7/api_keys": ["unexpected"]})
    result = await create_user_api_key(cast(AutomoxClient, client), org_id=42, user_id=7, name="k")
    assert result["data"]["created"] is True
    _, _path, body = client.calls[0]
    assert body == {"name": "k"}  # no expires_at key when omitted


@pytest.mark.asyncio
async def test_get_user_non_mapping_returns_empty():
    client = StubClient(get_responses={"/users/7": ["unexpected"]})
    result = await get_user(cast(AutomoxClient, client), org_id=42, user_id=7)
    assert result["data"] == {}


# ---------------------------------------------------------------------------
# Global (account-scoped) API keys — no decrypt (issue #91 category B)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_global_api_keys_projects_metadata():
    payload = {
        "size": 1,
        "results": [
            {"id": 5, "name": "Global CI", "is_enabled": True, "user": {"id": 1}},
        ],
    }
    client = StubClient(get_responses={"/global/api_keys": [payload]})
    result = await list_global_api_keys(cast(AutomoxClient, client))
    assert result["data"]["total_keys"] == 1
    key = result["data"]["api_keys"][0]
    assert key["name"] == "Global CI"
    assert "user" not in key


@pytest.mark.asyncio
async def test_list_global_api_keys_non_mapping():
    client = StubClient(get_responses={"/global/api_keys": ["unexpected"]})
    result = await list_global_api_keys(cast(AutomoxClient, client))
    assert result["data"]["total_keys"] == 0


@pytest.mark.asyncio
async def test_create_global_api_key_metadata_no_secret():
    created = {"id": 9, "name": "g", "is_enabled": True, "api_key": "SHOULD-NOT-APPEAR"}
    client = StubClient(post_responses={"/global/api_keys": [created]})
    result = await create_global_api_key(cast(AutomoxClient, client), name="g")
    assert result["data"]["created"] is True
    assert "api_key" not in result["data"]
    assert "not be retrieved" in result["metadata"]["note"]
    _, path, body = client.calls[0]
    assert path == "/global/api_keys"
    assert body == {"name": "g"}  # no expires_at when omitted


@pytest.mark.asyncio
async def test_update_global_api_key_toggles_enabled():
    rec = {"id": 5, "name": "g", "is_enabled": False}
    client = StubClient(put_responses={"/global/api_keys/5": [rec]})
    result = await update_global_api_key(cast(AutomoxClient, client), key_id=5, is_enabled=False)
    assert result["data"]["updated"] is True
    assert result["data"]["is_enabled"] is False
    _, _path, body = client.calls[0]
    assert body == {"is_enabled": False}


@pytest.mark.asyncio
async def test_delete_global_api_key():
    client = StubClient(delete_responses={"/global/api_keys/5": [None]})
    result = await delete_global_api_key(cast(AutomoxClient, client), key_id=5)
    assert result["data"]["deleted"] is True
    assert result["data"]["key_id"] == 5
