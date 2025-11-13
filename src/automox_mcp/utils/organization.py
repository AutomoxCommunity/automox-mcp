"""Organization-related helper functions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from automox_mcp.client import AutomoxClient


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _candidate_org_sequences(payload: Any) -> Sequence[Any]:
    if isinstance(payload, Sequence):
        return payload
    if isinstance(payload, Mapping):
        for key in ("orgs", "organizations", "data", "items", "results"):
            value = payload.get(key)
            if isinstance(value, Sequence):
                return value
    return ()


async def resolve_org_uuid(
    client: AutomoxClient,
    *,
    explicit_uuid: str | UUID | None = None,
    org_id: int | None = None,
    allow_account_uuid: bool = False,
) -> str:
    """Resolve the Automox organization UUID for the active context.

    Resolution order:
        1. Explicit UUID provided by the caller (string or UUID)
        2. Cached value on the client instance (`client.org_uuid`)
        3. Lookup via `/orgs` using the supplied org_id or `client.org_id`
        4. Optional fallback to the Automox account UUID when allowed
    """

    if explicit_uuid:
        uuid_text = str(explicit_uuid).strip()
        if not uuid_text:
            raise ValueError("org_uuid cannot be blank")
        client.org_uuid = uuid_text
        return uuid_text

    if client.org_uuid:
        return client.org_uuid

    resolved_org_id = org_id or client.org_id
    if resolved_org_id is None:
        if allow_account_uuid and client.account_uuid:
            account_text = str(client.account_uuid).strip()
            if account_text:
                client.org_uuid = account_text
                return account_text
        raise ValueError(
            "org_id required to resolve organization UUID - pass org_id explicitly or set "
            "AUTOMOX_ORG_ID."
        )

    orgs_payload = await client.get("/orgs", api="console")
    for candidate in _candidate_org_sequences(orgs_payload):
        if not isinstance(candidate, Mapping):
            continue
        candidate_id = (
            candidate.get("id")
            or candidate.get("org_id")
            or candidate.get("organization_id")
            or candidate.get("organizationId")
        )
        candidate_id_int = _coerce_int(candidate_id)
        if candidate_id_int != resolved_org_id:
            continue

        candidate_uuid = (
            candidate.get("org_uuid")
            or candidate.get("organization_uuid")
            or candidate.get("uuid")
            or candidate.get("organization_uid")
        )
        if candidate_uuid:
            uuid_text = str(candidate_uuid).strip()
            if uuid_text:
                client.org_uuid = uuid_text
                return uuid_text

    if allow_account_uuid and client.account_uuid:
        account_text = str(client.account_uuid).strip()
        if account_text:
            client.org_uuid = account_text
            return account_text

    raise ValueError(
        f"Unable to resolve organization UUID for org_id={resolved_org_id}. "
        "Verify the Automox credentials and organization scope."
    )


__all__ = ["resolve_org_uuid"]
