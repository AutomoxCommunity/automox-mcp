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
    page: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """List API keys for the organization (names and IDs only, secrets redacted)."""
    params: dict[str, Any] = {}
    if page is not None:
        params["page"] = page
    if limit is not None:
        params["limit"] = limit
    response = await client.get(f"/orgs/{org_id}/api_keys", params=params or None)

    # GET /orgs/{id}/api_keys returns a {"results": [...], "size": N} envelope
    # (confirmed live 2026-06-05: size=21, results carried 21 items). The
    # previous bare-list assumption made every conforming response collapse to
    # zero keys — the same envelope class as #154 (/approvals) and #163
    # (/data-extracts). Keep a bare-list fallback for defensive parity.
    size: int | None = None
    if isinstance(response, Mapping):
        raw_results = response.get("results")
        results = raw_results if isinstance(raw_results, list) else []
        raw_size = response.get("size")
        if isinstance(raw_size, int):
            size = raw_size
    elif isinstance(response, list):
        results = response
    else:
        results = []

    keys: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, Mapping):
            continue
        entry: dict[str, Any] = {
            "id": item.get("id"),
            "name": item.get("name"),
        }
        # Live DTO key is `is_enabled` (bool), NOT `enabled`; the prior code
        # read a key the API never returns. created_at/expires_at confirmed
        # live. The `user` blob (id/email/firstname/lastname) is dropped to
        # stay lean and avoid forwarding embedded contact PII.
        for optional in ("created_at", "expires_at", "last_used_at", "is_enabled"):
            val = item.get(optional)
            if val is not None:
                entry[optional] = val
        keys.append(entry)

    metadata: dict[str, Any] = {"deprecated_endpoint": False}
    if size is not None:
        metadata["total_size"] = size

    return {
        "data": {
            "total_keys": len(keys),
            "api_keys": keys,
        },
        "metadata": metadata,
    }


# Fields projected from the Organization DTO. Surfacing tier/capacity/parent so an
# LLM can navigate MSP org trees, check feature tiers, and flag trial/limit posture.
_ORG_FIELDS = (
    "id",
    "uuid",
    "name",
    "tier",
    "device_count",
    "device_limit",
    "soft_device_limit",
    "parent_id",
    "trial_end_time",
    "create_time",
)


async def list_organizations(
    client: AutomoxClient,
    *,
    page: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """List organizations visible to the API key with tier/capacity/parent detail."""
    params: dict[str, Any] = {}
    if page is not None:
        params["page"] = page
    if limit is not None:
        params["limit"] = limit
    results = await client.get("/orgs", params=params or None)

    if not isinstance(results, list):
        results = []

    orgs: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, Mapping):
            continue
        orgs.append({key: item.get(key) for key in _ORG_FIELDS if item.get(key) is not None})

    return {
        "data": {
            "total_organizations": len(orgs),
            "organizations": orgs,
        },
        "metadata": {
            "deprecated_endpoint": False,
        },
    }


# ---------------------------------------------------------------------------
# Identity inspection — read-only (issue #91 category A)
#
# SECURITY: the User DTO carries `intercom_hmac` (a chat-auth HMAC) and the
# zone DTO carries `access_key`. Both are secrets and are deliberately excluded
# from every projection below — never surface them to the model.
# ---------------------------------------------------------------------------

# Lean projection for the user *list* (avoids per-user org/group blobs).
_USER_LIST_FIELDS = (
    "id",
    "firstname",
    "lastname",
    "email",
    "account_id",
    "account_name",
    "account_rbac_roles",
    "rbac_roles",
    "tfa_type",
)
# Fuller projection for a single-user detail view.
_USER_DETAIL_FIELDS = (
    *_USER_LIST_FIELDS,
    "orgs",
    "server_groups",
    "tags",
    "saml_enabled",
    "sso_enabled",
    "account_created_at",
)
# Projection for zone-member User DTOs (list_zone_users). The zone-users endpoint
# returns the same User DTO that carries `intercom_hmac` (see SECURITY note above),
# so it MUST be projected like every other user listing rather than forwarded raw.
# Allowlist (deny-by-default): identity + RBAC roles + the membership key, plus
# `uuid` if the endpoint emits one (the account-user UUID the UUID-keyed tools need
# — see issue #193). `intercom_hmac` is absent from the allowlist and so dropped.
_ZONE_USER_FIELDS = (
    *_USER_LIST_FIELDS,
    "user_id",
    "uuid",
)
_ZONE_FIELDS = (
    "id",
    "organization_id",
    "account_id",
    "parent_id",
    "name",
    "created_by",
    "created_at",
    "updated_at",
)
# The zone DTO's `created_by` is a nested *User* blob (email, names,
# two_factor_authentication, RBAC role). Surfacing it raw — especially across a
# list endpoint that returns many zones at once — leaks user PII. Re-project it
# through this allowlist so only a non-PII actor reference (id + display name)
# survives; never email, 2FA, or RBAC role. Mirrors the nested-org redaction in
# get_user (see _USER_ORG_FIELDS).
_ZONE_CREATED_BY_FIELDS = (
    "id",
    "user_id",
    "firstname",
    "lastname",
)
# Nested org projection for get_user.orgs[]. The User DTO forwards each org
# whole, and an org object can carry `access_key` (a per-org credential) plus
# `saml`/`metadata` config blobs. Project an allowlist of navigation-safe
# fields so a populated secret is never forwarded into model context, mirroring
# the _ZONE_FIELDS redaction guarantee. (The /users endpoint is scope-gated on
# the audit key, so the no-access_key witness is implemented defensively rather
# than live-confirmed.)
_USER_ORG_FIELDS = (
    "id",
    "uuid",
    "name",
    "plan",  # kept so the orgs[].plan legend (below) stays meaningful
    "device_count",
    "device_limit",
    "soft_device_limit",
    "parent_id",
    "create_time",
)


def _project(item: Mapping[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {key: item.get(key) for key in fields if item.get(key) is not None}


def _project_zone(item: Mapping[str, Any]) -> dict[str, Any]:
    """Project a zone DTO through the allowlist (drops `access_key`) and
    re-project its nested `created_by` user blob down to a non-PII actor
    reference. Shared by every zone read/write path so the redaction guarantee
    holds uniformly (see SECURITY note above)."""
    zone = _project(item, _ZONE_FIELDS)
    created_by = zone.get("created_by")
    if isinstance(created_by, Mapping):
        zone["created_by"] = _project(created_by, _ZONE_CREATED_BY_FIELDS)
    return zone


def _envelope(response: Any) -> tuple[list[Any], dict[str, Any]]:
    """Split an Automox ``{data: [...], metadata: {...}}`` envelope."""
    if isinstance(response, Mapping):
        raw = response.get("data")
        data = list(raw) if isinstance(raw, list) else []
        meta = response.get("metadata")
        return data, dict(meta) if isinstance(meta, Mapping) else {}
    if isinstance(response, list):
        return list(response), {}
    return [], {}


async def list_users(
    client: AutomoxClient,
    *,
    org_id: int,
    page: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """List users in the organization (lean projection; secrets redacted)."""
    params: dict[str, Any] = {"o": org_id}
    if page is not None:
        params["page"] = page
    if limit is not None:
        params["limit"] = limit
    response = await client.get("/users", params=params)

    raw = response if isinstance(response, list) else []
    users = [_project(u, _USER_LIST_FIELDS) for u in raw if isinstance(u, Mapping)]

    return {
        "data": {"total_users": len(users), "users": users},
        "metadata": {"deprecated_endpoint": False},
    }


async def get_user(
    client: AutomoxClient,
    *,
    org_id: int,
    user_id: int,
) -> dict[str, Any]:
    """Get a single user by numeric ID (detail projection; secrets redacted)."""
    response = await client.get(f"/users/{user_id}", params={"o": org_id})
    detail = _project(response, _USER_DETAIL_FIELDS) if isinstance(response, Mapping) else {}

    # orgs[] is forwarded whole by _USER_DETAIL_FIELDS; re-project each nested
    # org through an allowlist so a populated access_key/saml/metadata is never
    # leaked into model context (see _USER_ORG_FIELDS).
    raw_orgs = detail.get("orgs")
    if isinstance(raw_orgs, list):
        detail["orgs"] = [_project(o, _USER_ORG_FIELDS) for o in raw_orgs if isinstance(o, Mapping)]

    return {
        "data": detail,
        "metadata": {
            "deprecated_endpoint": False,
            "field_notes": {
                "orgs[].plan": (
                    "Per-org billing-plan slug (per spec: basic/manage/tier3 — "
                    "spec-only, unverified live; field absent on some tenants). "
                    "Distinct vocabulary from list_organizations Organization.tier; "
                    "do not reconcile or rank them."
                )
            },
        },
    }


async def get_account(
    client: AutomoxClient,
    *,
    account_id: str | UUID,
) -> dict[str, Any]:
    """Get account detail (id, name, type, timestamps)."""
    response = await client.get(f"/accounts/{account_id}")
    detail: dict[str, Any] = dict(response) if isinstance(response, Mapping) else {}

    return {
        "data": detail,
        "metadata": {"deprecated_endpoint": False, "account_id": str(account_id)},
    }


async def list_account_rbac_roles(
    client: AutomoxClient,
    *,
    account_id: str | UUID,
) -> dict[str, Any]:
    """List the RBAC roles available in the account."""
    response = await client.get(f"/accounts/{account_id}/rbac-roles")
    roles, meta = _envelope(response)
    meta["deprecated_endpoint"] = False
    meta["account_id"] = str(account_id)

    return {
        "data": {"total_roles": len(roles), "rbac_roles": roles},
        "metadata": meta,
    }


async def get_account_user(
    client: AutomoxClient,
    *,
    account_id: str | UUID,
    user_id: str | UUID,
) -> dict[str, Any]:
    """Get an account-scoped user record (status, RBAC role, verification)."""
    response = await client.get(f"/accounts/{account_id}/users/{user_id}")
    detail: dict[str, Any] = dict(response) if isinstance(response, Mapping) else {}

    return {
        "data": detail,
        "metadata": {
            "deprecated_endpoint": False,
            "account_id": str(account_id),
            "field_notes": {
                "two_factor_authentication": (
                    "The literal string 'disabled' means 2FA is OFF (live-verified "
                    "2026-06-05 — the field carries 'disabled', NOT null, when 2FA is "
                    "not enabled). Other string values (e.g. 'email'/'google' per spec, "
                    "not live-verified) name the configured 2FA type, i.e. 2FA is ON. "
                    "Do NOT read the string 'disabled' as a configured 2FA type — it "
                    "means the opposite. null or absent remains AMBIGUOUS (field is "
                    "non-required): may mean disabled OR not-reported, so do not assert "
                    "2FA is enabled or disabled from a null/missing value."
                )
            },
        },
    }


async def list_zones_for_user(
    client: AutomoxClient,
    *,
    account_id: str | UUID,
    user_id: str | UUID,
) -> dict[str, Any]:
    """List the zones a given user belongs to."""
    response = await client.get(f"/accounts/{account_id}/users/{user_id}/zones")
    zones, meta = _envelope(response)
    # SECURITY: project each zone through the allowlist so `access_key` and the
    # nested `created_by` user PII are never forwarded raw (mirrors get_zone).
    zones = [_project_zone(z) for z in zones if isinstance(z, Mapping)]
    meta["deprecated_endpoint"] = False
    meta["account_id"] = str(account_id)

    return {
        "data": {"user_id": str(user_id), "total_zones": len(zones), "zones": zones},
        "metadata": meta,
    }


async def list_zones(
    client: AutomoxClient,
    *,
    account_id: str | UUID,
    page: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """List the zones (organizations) in the account."""
    params: dict[str, Any] = {}
    if page is not None:
        params["page"] = page
    if limit is not None:
        params["limit"] = limit
    response = await client.get(f"/accounts/{account_id}/zones", params=params or None)
    zones, meta = _envelope(response)
    # SECURITY: project each zone through the allowlist so `access_key` and the
    # nested `created_by` user PII are never forwarded raw (mirrors get_zone).
    zones = [_project_zone(z) for z in zones if isinstance(z, Mapping)]
    meta["deprecated_endpoint"] = False
    meta["account_id"] = str(account_id)

    return {
        "data": {"total_zones": len(zones), "zones": zones},
        "metadata": meta,
    }


async def get_zone(
    client: AutomoxClient,
    *,
    account_id: str | UUID,
    zone_id: str | UUID,
) -> dict[str, Any]:
    """Get a single zone by UUID (access_key redacted)."""
    response = await client.get(f"/accounts/{account_id}/zones/{zone_id}")
    detail = _project_zone(response) if isinstance(response, Mapping) else {}

    return {
        "data": detail,
        "metadata": {"deprecated_endpoint": False, "account_id": str(account_id)},
    }


async def list_zone_users(
    client: AutomoxClient,
    *,
    account_id: str | UUID,
    zone_id: str | UUID,
    page: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """List the users assigned to a given zone."""
    params: dict[str, Any] = {}
    if page is not None:
        params["page"] = page
    if limit is not None:
        params["limit"] = limit
    response = await client.get(
        f"/accounts/{account_id}/zones/{zone_id}/users", params=params or None
    )
    users, meta = _envelope(response)
    # SECURITY: project each zone-member User DTO through the allowlist so the
    # `intercom_hmac` secret it carries is never forwarded to the model (the raw
    # `_envelope` forward previously surfaced it — there is no downstream redaction
    # for `intercom_hmac`). Mirrors list_users / get_user.
    users = [_project(u, _ZONE_USER_FIELDS) for u in users if isinstance(u, Mapping)]
    meta["deprecated_endpoint"] = False
    meta["account_id"] = str(account_id)

    return {
        "data": {"zone_id": str(zone_id), "total_users": len(users), "users": users},
        "metadata": meta,
    }


# ---------------------------------------------------------------------------
# Identity / zone / per-user-key writes (issue #91 category A, write slice)
#
# SECURITY: API-key endpoints never return the secret value (verified against
# the DTOs — create/get/update return metadata only), and create_zone's
# access_key is redacted via _ZONE_FIELDS. update_user deliberately cannot set
# passwords.
# ---------------------------------------------------------------------------

# Safe per-key metadata projection (the `user` blob is dropped to stay lean).
_API_KEY_FIELDS = ("id", "name", "is_enabled", "expires_at", "created_at")


def _project_key(item: Mapping[str, Any]) -> dict[str, Any]:
    return {key: item.get(key) for key in _API_KEY_FIELDS if item.get(key) is not None}


async def create_zone(
    client: AutomoxClient,
    *,
    account_id: str | UUID,
    name: str,
) -> dict[str, Any]:
    """Create a new zone (organization) in the account. access_key is redacted."""
    response = await client.post(f"/accounts/{account_id}/zones", json_data={"name": name})
    detail = _project_zone(response) if isinstance(response, Mapping) else {}
    detail["created"] = True

    return {
        "data": detail,
        "metadata": {"deprecated_endpoint": False, "account_id": str(account_id)},
    }


async def update_user(
    client: AutomoxClient,
    *,
    user_id: int,
    firstname: str | None = None,
    lastname: str | None = None,
    email: str | None = None,
    tfa_type: str | None = None,
) -> dict[str, Any]:
    """Partially update a user's profile fields (never passwords)."""
    body: dict[str, Any] = {}
    for key, value in (
        ("firstname", firstname),
        ("lastname", lastname),
        ("email", email),
        ("tfa_type", tfa_type),
    ):
        if value is not None:
            body[key] = value

    await client.patch(f"/users/{user_id}", json_data=body)

    return {
        "data": {"user_id": user_id, "updated": True, "fields_updated": sorted(body)},
        "metadata": {"deprecated_endpoint": False},
    }


async def list_user_api_keys(
    client: AutomoxClient,
    *,
    org_id: int,
    user_id: int,
    page: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """List a user's API keys (metadata only — secrets are never returned)."""
    params: dict[str, Any] = {"o": org_id}
    if page is not None:
        params["page"] = page
    if limit is not None:
        params["limit"] = limit
    response = await client.get(f"/users/{user_id}/api_keys", params=params)

    raw = response.get("results") if isinstance(response, Mapping) else response
    items = raw if isinstance(raw, list) else []
    keys = [_project_key(k) for k in items if isinstance(k, Mapping)]

    return {
        "data": {"user_id": user_id, "total_keys": len(keys), "api_keys": keys},
        "metadata": {"deprecated_endpoint": False},
    }


async def get_user_api_key(
    client: AutomoxClient,
    *,
    org_id: int,
    user_id: int,
    key_id: int,
) -> dict[str, Any]:
    """Get one user API key by ID (metadata only — secret never returned)."""
    response = await client.get(f"/users/{user_id}/api_keys/{key_id}", params={"o": org_id})
    detail = _project_key(response) if isinstance(response, Mapping) else {}

    return {
        "data": detail,
        "metadata": {"deprecated_endpoint": False},
    }


async def create_user_api_key(
    client: AutomoxClient,
    *,
    org_id: int,
    user_id: int,
    name: str,
    expires_at: str | None = None,
) -> dict[str, Any]:
    """Create a user API key. Returns metadata only — the secret is never
    surfaced (and is not retrievable via MCP, by design)."""
    body: dict[str, Any] = {"name": name}
    if expires_at is not None:
        body["expires_at"] = expires_at

    response = await client.post(f"/users/{user_id}/api_keys", json_data=body, params={"o": org_id})
    detail = _project_key(response) if isinstance(response, Mapping) else {}
    detail["created"] = True

    return {
        "data": detail,
        "metadata": {
            "deprecated_endpoint": False,
            "note": "The API key secret is not returned and cannot be retrieved via MCP.",
        },
    }


async def update_user_api_key(
    client: AutomoxClient,
    *,
    org_id: int,
    user_id: int,
    key_id: int,
    is_enabled: bool,
) -> dict[str, Any]:
    """Enable or disable a user API key (metadata only)."""
    response = await client.put(
        f"/users/{user_id}/api_keys/{key_id}",
        json_data={"is_enabled": is_enabled},
        params={"o": org_id},
    )
    detail = _project_key(response) if isinstance(response, Mapping) else {}
    detail["updated"] = True

    return {
        "data": detail,
        "metadata": {"deprecated_endpoint": False},
    }


async def delete_user_api_key(
    client: AutomoxClient,
    *,
    org_id: int,
    user_id: int,
    key_id: int,
) -> dict[str, Any]:
    """Delete a user API key by ID."""
    await client.delete(f"/users/{user_id}/api_keys/{key_id}", params={"o": org_id})

    return {
        "data": {"user_id": user_id, "key_id": key_id, "deleted": True},
        "metadata": {"deprecated_endpoint": False},
    }


# ---------------------------------------------------------------------------
# Global (account-scoped) API keys — no decrypt (issue #91 category B)
#
# These are account-level credentials (higher blast radius than user keys).
# create/update never return the secret (verified against the DTOs); the
# decrypt endpoint is deliberately not wrapped.
# ---------------------------------------------------------------------------


async def list_global_api_keys(client: AutomoxClient) -> dict[str, Any]:
    """List global (account-scoped) API keys — metadata only, secrets redacted."""
    response = await client.get("/global/api_keys")
    raw = response.get("results") if isinstance(response, Mapping) else response
    items = raw if isinstance(raw, list) else []
    keys = [_project_key(k) for k in items if isinstance(k, Mapping)]

    return {
        "data": {"total_keys": len(keys), "api_keys": keys},
        "metadata": {"deprecated_endpoint": False},
    }


async def create_global_api_key(
    client: AutomoxClient,
    *,
    name: str,
    expires_at: str | None = None,
) -> dict[str, Any]:
    """Create a global API key. Returns metadata only — the secret is never
    surfaced and cannot be retrieved via MCP."""
    body: dict[str, Any] = {"name": name}
    if expires_at is not None:
        body["expires_at"] = expires_at

    response = await client.post("/global/api_keys", json_data=body)
    detail = _project_key(response) if isinstance(response, Mapping) else {}
    detail["created"] = True

    return {
        "data": detail,
        "metadata": {
            "deprecated_endpoint": False,
            "note": "The API key secret is not returned and cannot be retrieved via MCP.",
        },
    }


async def update_global_api_key(
    client: AutomoxClient,
    *,
    key_id: int,
    is_enabled: bool,
) -> dict[str, Any]:
    """Enable or disable a global API key (metadata only)."""
    response = await client.put(f"/global/api_keys/{key_id}", json_data={"is_enabled": is_enabled})
    detail = _project_key(response) if isinstance(response, Mapping) else {}
    detail["updated"] = True

    return {
        "data": detail,
        "metadata": {"deprecated_endpoint": False},
    }


async def delete_global_api_key(
    client: AutomoxClient,
    *,
    key_id: int,
) -> dict[str, Any]:
    """Delete a global API key by ID."""
    await client.delete(f"/global/api_keys/{key_id}")

    return {
        "data": {"key_id": key_id, "deleted": True},
        "metadata": {"deprecated_endpoint": False},
    }
