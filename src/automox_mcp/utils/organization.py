"""Organization-related helper functions."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from ..client import AutomoxClient

logger = logging.getLogger(__name__)

# Lock to prevent concurrent mutations of client.org_uuid
_org_uuid_lock = asyncio.Lock()


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _candidate_org_sequences(payload: Any) -> Sequence[Any]:
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        return payload
    if isinstance(payload, Mapping):
        for key in ("orgs", "organizations", "data", "items", "results"):
            value = payload.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
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

    async with _org_uuid_lock:
        if explicit_uuid:
            uuid_text = str(explicit_uuid).strip()
            if not uuid_text:
                raise ValueError("org_uuid cannot be blank")
            # S-004: Validate UUID format before returning to prevent malformed values.
            # Do NOT cache caller-supplied UUIDs on client.org_uuid — the client is a
            # shared singleton across tool invocations, and caching here would let one
            # tool's explicit_uuid leak into another tool's call for a different org.
            UUID(uuid_text)
            return uuid_text

        resolved_org_id = org_id or client.org_id

        # Only return the cached client.org_uuid when the caller is asking about the
        # same org the cache was populated for. Otherwise (multi-org API key with
        # per-call org_id), fall through to a fresh /orgs lookup to avoid returning a
        # UUID that belongs to a different tenant.
        if client.org_uuid and (resolved_org_id is None or resolved_org_id == client.org_id):
            return client.org_uuid

        if resolved_org_id is None:
            if allow_account_uuid and client.account_uuid:
                account_text = str(client.account_uuid).strip()
                if account_text:
                    # Cache account UUID separately — do NOT set client.org_uuid
                    # to prevent poisoning the cache for calls that require a real
                    # org UUID.
                    logger.debug("Using account UUID as fallback (allow_account_uuid=True)")
                    return account_text
            raise ValueError(
                "org_id required to resolve organization UUID - pass org_id explicitly or set "
                "AUTOMOX_ORG_ID."
            )

        orgs_payload = await client.get("/orgs")
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
                    # Validate UUID format before caching (matches explicit_uuid path)
                    UUID(uuid_text)
                    # Cache on the client only when the resolved org matches the
                    # client's configured org_id; otherwise the cache would poison
                    # subsequent calls that target the configured org.
                    if resolved_org_id == client.org_id:
                        client.org_uuid = uuid_text
                    return uuid_text

        if allow_account_uuid and client.account_uuid:
            account_text = str(client.account_uuid).strip()
            if account_text:
                # Don't cache account UUID as org UUID — return without caching
                logger.debug(
                    "Using account UUID as fallback after /orgs lookup (allow_account_uuid=True)"
                )
                return account_text

        raise ValueError(
            f"Unable to resolve organization UUID for org_id={resolved_org_id}. "
            "Verify the Automox credentials and organization scope."
        )


__all__ = ["resolve_org_uuid"]
