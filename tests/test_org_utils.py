from typing import cast

import pytest

from automox_mcp.client import AutomoxClient
from automox_mcp.utils.organization import resolve_org_uuid


class StubClient:
    def __init__(
        self,
        *,
        org_id: int | None = None,
        org_uuid: str | None = None,
        account_uuid: str | None = None,
        responses: dict[str, object] | None = None,
    ) -> None:
        self.org_id = org_id
        self.org_uuid = org_uuid
        self.account_uuid = account_uuid
        self._responses = responses or {}

    async def get(self, path: str, *, params=None, headers=None, api=None):
        return self._responses.get(path)


@pytest.mark.asyncio
async def test_resolve_org_uuid_prefers_explicit():
    stub = StubClient(org_id=10)
    client = cast(AutomoxClient, stub)
    value = await resolve_org_uuid(client, explicit_uuid="12345678-1234-1234-1234-1234567890ab")
    assert value == "12345678-1234-1234-1234-1234567890ab"
    assert client.org_uuid == "12345678-1234-1234-1234-1234567890ab"


@pytest.mark.asyncio
async def test_resolve_org_uuid_uses_cached_value():
    cached = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    stub = StubClient(org_id=10, org_uuid=cached)
    client = cast(AutomoxClient, stub)
    value = await resolve_org_uuid(client)
    assert value == cached


@pytest.mark.asyncio
async def test_resolve_org_uuid_fetches_from_orgs():
    org_uuid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    stub = StubClient(
        org_id=42,
        responses={
            "/orgs": [
                {"id": 1, "org_uuid": "cccccccc-cccc-cccc-cccc-cccccccccccc"},
                {"id": 42, "org_uuid": org_uuid},
            ]
        },
    )
    client = cast(AutomoxClient, stub)
    value = await resolve_org_uuid(client)
    assert value == org_uuid
    assert client.org_uuid == org_uuid


@pytest.mark.asyncio
async def test_resolve_org_uuid_falls_back_to_account_uuid_when_allowed():
    account_uuid = "dddddddd-dddd-dddd-dddd-dddddddddddd"
    stub = StubClient(org_id=None, account_uuid=account_uuid)
    client = cast(AutomoxClient, stub)
    value = await resolve_org_uuid(client, allow_account_uuid=True)
    assert value == account_uuid
    assert client.org_uuid == account_uuid


@pytest.mark.asyncio
async def test_resolve_org_uuid_raises_when_missing_context():
    stub = StubClient(org_id=None, account_uuid=None)
    client = cast(AutomoxClient, stub)
    with pytest.raises(ValueError):
        await resolve_org_uuid(client)


@pytest.mark.asyncio
async def test_resolve_org_uuid_raises_on_blank_explicit_uuid():
    stub = StubClient(org_id=10)
    client = cast(AutomoxClient, stub)
    # An explicit_uuid of all-whitespace triggers the blank check
    with pytest.raises(ValueError, match="org_uuid cannot be blank"):
        await resolve_org_uuid(client, explicit_uuid="   ")


@pytest.mark.asyncio
async def test_resolve_org_uuid_fallback_to_account_uuid_after_orgs_lookup():
    """When /orgs returns no match but allow_account_uuid=True, use account_uuid."""
    account_uuid = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
    stub = StubClient(
        org_id=99,
        account_uuid=account_uuid,
        responses={
            "/orgs": [
                {"id": 1, "org_uuid": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"},
            ]
        },
    )
    client = cast(AutomoxClient, stub)
    value = await resolve_org_uuid(client, allow_account_uuid=True)
    assert value == account_uuid
    assert client.org_uuid == account_uuid


@pytest.mark.asyncio
async def test_resolve_org_uuid_raises_when_lookup_fails_and_no_fallback():
    """When /orgs returns no match and allow_account_uuid=False, raise ValueError."""
    stub = StubClient(
        org_id=99,
        responses={
            "/orgs": [
                {"id": 1, "org_uuid": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"},
            ]
        },
    )
    client = cast(AutomoxClient, stub)
    with pytest.raises(ValueError, match="Unable to resolve organization UUID"):
        await resolve_org_uuid(client, allow_account_uuid=False)


@pytest.mark.asyncio
async def test_candidate_org_sequences_with_mapping_payload():
    """Verify _candidate_org_sequences handles dict payloads with known keys."""
    from automox_mcp.utils.organization import _candidate_org_sequences

    # Should find orgs list under 'data' key
    payload = {"data": [{"id": 1}, {"id": 2}]}
    result = _candidate_org_sequences(payload)
    assert len(result) == 2

    # Should find orgs list under 'orgs' key
    payload2 = {"orgs": [{"id": 3}]}
    result2 = _candidate_org_sequences(payload2)
    assert len(result2) == 1


def test_coerce_int_with_invalid_value():
    """_coerce_int returns None for non-integer inputs."""
    from automox_mcp.utils.organization import _coerce_int

    assert _coerce_int("not-an-int") is None
    assert _coerce_int(None) is None
    assert _coerce_int("") is None


@pytest.mark.asyncio
async def test_resolve_org_uuid_with_mapping_orgs_response():
    """Verify resolution works when /orgs returns a dict (not a list)."""
    org_uuid = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    stub = StubClient(
        org_id=5,
        responses={"/orgs": {"data": [{"id": 5, "org_uuid": org_uuid}]}},
    )
    client = cast(AutomoxClient, stub)
    value = await resolve_org_uuid(client)
    assert value == org_uuid
