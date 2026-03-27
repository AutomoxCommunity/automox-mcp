"""Tests for audit service v2 (OCSF) workflows."""

from typing import Any, cast

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.audit_v2 import audit_events_ocsf

_ORG_UUID = "11111111-2222-3333-4444-555555555555"

_OCSF_EVENTS = [
    {
        "uid": "evt-001",
        "time": "2026-03-25T10:00:00Z",
        "category_uid": 3,
        "category_name": "authentication",
        "type_uid": 3001,
        "type_name": "Authentication: Logon",
        "activity": "Logon",
        "message": "User logged in",
        "severity": "Informational",
        "status": "Success",
        "actor": {
            "user": {
                "email_addr": "admin@example.com",
                "name": "Admin User",
                "uid": "user-001",
            },
        },
    },
    {
        "uid": "evt-002",
        "time": "2026-03-25T11:00:00Z",
        "category_uid": 6,
        "category_name": "entity_management",
        "type_uid": 6001,
        "type_name": "Entity Management: Create",
        "activity": "Create",
        "message": "Policy created",
        "severity": "Informational",
        "status": "Success",
        "resource": {
            "uid": "pol-001",
            "name": "New Policy",
            "type": "policy",
        },
    },
]


def _make_client(**kwargs: Any) -> StubClient:
    client = StubClient(**kwargs)
    client.org_uuid = _ORG_UUID
    return client


# ---------------------------------------------------------------------------
# audit_events_ocsf
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_returns_all_events() -> None:
    path = f"/audit-service/v1/orgs/{_ORG_UUID}/events"
    client = _make_client(get_responses={path: [_OCSF_EVENTS]})
    result = await audit_events_ocsf(
        cast(AutomoxClient, client),
        org_id=42,
        date="2026-03-25",
    )

    assert result["data"]["total_events"] == 2
    assert result["data"]["date"] == "2026-03-25"
    assert result["data"]["org_uuid"] == _ORG_UUID


@pytest.mark.asyncio
async def test_extracts_actor_info() -> None:
    path = f"/audit-service/v1/orgs/{_ORG_UUID}/events"
    client = _make_client(get_responses={path: [_OCSF_EVENTS]})
    result = await audit_events_ocsf(
        cast(AutomoxClient, client),
        org_id=42,
        date="2026-03-25",
    )

    auth_event = result["data"]["events"][0]
    assert auth_event["actor"]["email_addr"] == "admin@example.com"
    assert auth_event["actor"]["name"] == "Admin User"


@pytest.mark.asyncio
async def test_extracts_resource_info() -> None:
    path = f"/audit-service/v1/orgs/{_ORG_UUID}/events"
    client = _make_client(get_responses={path: [_OCSF_EVENTS]})
    result = await audit_events_ocsf(
        cast(AutomoxClient, client),
        org_id=42,
        date="2026-03-25",
    )

    entity_event = result["data"]["events"][1]
    assert entity_event["resource"]["name"] == "New Policy"


@pytest.mark.asyncio
async def test_filters_by_category_name() -> None:
    path = f"/audit-service/v1/orgs/{_ORG_UUID}/events"
    client = _make_client(get_responses={path: [_OCSF_EVENTS]})
    result = await audit_events_ocsf(
        cast(AutomoxClient, client),
        org_id=42,
        date="2026-03-25",
        category_name="authentication",
    )

    assert result["data"]["total_events"] == 1
    assert result["data"]["events"][0]["category_name"] == "authentication"
    assert result["metadata"]["events_before_filter"] == 2


@pytest.mark.asyncio
async def test_filters_by_type_name() -> None:
    path = f"/audit-service/v1/orgs/{_ORG_UUID}/events"
    client = _make_client(get_responses={path: [_OCSF_EVENTS]})
    result = await audit_events_ocsf(
        cast(AutomoxClient, client),
        org_id=42,
        date="2026-03-25",
        type_name="Entity Management: Create",
    )

    assert result["data"]["total_events"] == 1


@pytest.mark.asyncio
async def test_passes_cursor_and_limit() -> None:
    path = f"/audit-service/v1/orgs/{_ORG_UUID}/events"
    client = _make_client(get_responses={path: [[]]})
    await audit_events_ocsf(
        cast(AutomoxClient, client),
        org_id=42,
        date="2026-03-25",
        cursor="abc123",
        limit=50,
    )

    params = client.calls[0][2]
    assert params["cursor"] == "abc123"
    assert params["limit"] == 50


@pytest.mark.asyncio
async def test_handles_wrapped_response() -> None:
    path = f"/audit-service/v1/orgs/{_ORG_UUID}/events"
    wrapped = {
        "data": _OCSF_EVENTS,
        "metadata": {"next": "cursor-xyz"},
    }
    client = _make_client(get_responses={path: [wrapped]})
    result = await audit_events_ocsf(
        cast(AutomoxClient, client),
        org_id=42,
        date="2026-03-25",
    )

    assert result["data"]["total_events"] == 2
    assert result["metadata"]["next_cursor"] == "cursor-xyz"


@pytest.mark.asyncio
async def test_handles_empty_response() -> None:
    path = f"/audit-service/v1/orgs/{_ORG_UUID}/events"
    client = _make_client(get_responses={path: [[]]})
    result = await audit_events_ocsf(
        cast(AutomoxClient, client),
        org_id=42,
        date="2026-03-25",
    )
    assert result["data"]["total_events"] == 0


@pytest.mark.asyncio
async def test_category_filter_case_insensitive() -> None:
    path = f"/audit-service/v1/orgs/{_ORG_UUID}/events"
    client = _make_client(get_responses={path: [_OCSF_EVENTS]})
    result = await audit_events_ocsf(
        cast(AutomoxClient, client),
        org_id=42,
        date="2026-03-25",
        category_name="AUTHENTICATION",
    )
    assert result["data"]["total_events"] == 1
