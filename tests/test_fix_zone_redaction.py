"""Regression tests for zone-list secret/PII redaction.

list_zones and list_zones_for_user previously forwarded raw zone DTOs straight
out of `_envelope`, leaking every zone's `access_key` secret and the nested
`created_by` user blob (email / two_factor_authentication / RBAC role) to the
model. Both list paths must now project each zone through the same allowlist
get_zone uses, dropping `access_key` and reducing `created_by` to a non-PII
actor reference (id + display name only).
"""

from __future__ import annotations

import json
from typing import cast

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.account import list_zones, list_zones_for_user

_ACCT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_USER = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

# Two zones, each carrying the `access_key` secret and a `created_by` blob that
# embeds user PII (email, 2FA state, RBAC role). Shaped after the get_zone
# fixture so the list paths are asserted against the same DTO expectations.
_ZONES = [
    {
        "id": "z1",
        "organization_id": 99,
        "account_id": 1,
        "name": "EU Zone",
        "access_key": "SECRET-ZONE-KEY-1",
        "created_by": {
            "id": 7,
            "firstname": "Ada",
            "lastname": "Lovelace",
            "email": "ada@example.com",
            "two_factor_authentication": "disabled",
            "rbac_role": "global-admin",
        },
    },
    {
        "id": "z2",
        "organization_id": 100,
        "account_id": 1,
        "name": "US Zone",
        "access_key": "SECRET-ZONE-KEY-2",
        "created_by": {
            "id": 8,
            "firstname": "Grace",
            "lastname": "Hopper",
            "email": "grace@example.com",
            "two_factor_authentication": "email",
            "rbac_role": "read-only",
        },
    },
]

# Secrets / PII that must NEVER appear anywhere in the serialized zone output.
_FORBIDDEN_SUBSTRINGS = (
    "SECRET-ZONE-KEY-1",
    "SECRET-ZONE-KEY-2",
    "ada@example.com",
    "grace@example.com",
    "two_factor_authentication",
    "rbac_role",
    "global-admin",
    "read-only",
)


def _assert_zones_redacted(zones: list[dict]) -> None:
    """Every zone keeps legitimate fields but leaks no secret/PII."""
    blob = json.dumps(zones)
    assert "access_key" not in blob
    for forbidden in _FORBIDDEN_SUBSTRINGS:
        assert forbidden not in blob, f"leaked: {forbidden}"

    for zone in zones:
        assert "access_key" not in zone
        # Legitimate zone fields survive the projection.
        assert zone["id"] in {"z1", "z2"}
        assert zone["name"] in {"EU Zone", "US Zone"}
        assert zone["organization_id"] in {99, 100}

        # created_by, if present, carries only a non-PII actor reference.
        created_by = zone["created_by"]
        assert created_by["id"] in {7, 8}
        assert created_by["firstname"] in {"Ada", "Grace"}
        assert "email" not in created_by
        assert "two_factor_authentication" not in created_by
        assert "rbac_role" not in created_by


@pytest.mark.asyncio
async def test_list_zones_redacts_access_key_and_created_by_pii():
    envelope = {"data": _ZONES, "metadata": {}}
    client = StubClient(get_responses={f"/accounts/{_ACCT}/zones": [envelope]})
    result = await list_zones(cast(AutomoxClient, client), account_id=_ACCT)

    zones = result["data"]["zones"]
    assert result["data"]["total_zones"] == 2
    _assert_zones_redacted(zones)


@pytest.mark.asyncio
async def test_list_zones_for_user_redacts_access_key_and_created_by_pii():
    envelope = {"data": _ZONES, "metadata": {}}
    client = StubClient(get_responses={f"/accounts/{_ACCT}/users/{_USER}/zones": [envelope]})
    result = await list_zones_for_user(cast(AutomoxClient, client), account_id=_ACCT, user_id=_USER)

    zones = result["data"]["zones"]
    assert result["data"]["total_zones"] == 2
    assert result["data"]["user_id"] == _USER
    _assert_zones_redacted(zones)
