"""Tests for audit service v2 (OCSF) workflows."""

from typing import Any, cast

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.audit_v2 import _ocsf_time_to_iso, audit_events_ocsf

_ORG_UUID = "11111111-2222-3333-4444-555555555555"

_OCSF_EVENTS = [
    # Shape mirrors the live audit-service payload (sanitized capture
    # 2026-06-05): `time` is epoch SECONDS as a float (not ISO, not the
    # OCSF-standard milliseconds), and events carry the integer
    # severity_id/status_id enums alongside (or instead of) string labels.
    {
        "uid": "evt-001",
        "time": 1774432800.123456,  # 2026-03-25T10:00:00Z
        "category_uid": 3,
        "category_name": "authentication",
        "type_uid": 3001,
        "type_name": "Authentication: Logon",
        "activity": "Logon",
        "message": "User logged in",
        "severity": "Informational",
        "severity_id": 1,
        "status": "Success",
        "status_id": 1,
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
        "time": 1774436400.0,  # 2026-03-25T11:00:00Z
        "category_uid": 6,
        "category_name": "entity_management",
        "type_uid": 6001,
        "type_name": "Entity Management: Create",
        "activity": "Create",
        "message": "Policy created",
        # String labels omitted — live events sometimes carry only the ids.
        "severity_id": 1,
        "status_id": 2,
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
async def test_time_converted_from_epoch_seconds_to_iso() -> None:
    # Upstream sends epoch seconds (live-verified 2026-06-05, despite OCSF
    # specifying milliseconds); the model must receive ISO 8601 UTC.
    path = f"/audit-service/v1/orgs/{_ORG_UUID}/events"
    client = _make_client(get_responses={path: [_OCSF_EVENTS]})
    result = await audit_events_ocsf(
        cast(AutomoxClient, client),
        org_id=42,
        date="2026-03-25",
    )

    events = result["data"]["events"]
    assert events[0]["time"] == "2026-03-25T10:00:00.123456Z"
    assert events[1]["time"] == "2026-03-25T11:00:00Z"


@pytest.mark.asyncio
async def test_enum_labels_filled_when_upstream_omits_strings() -> None:
    path = f"/audit-service/v1/orgs/{_ORG_UUID}/events"
    client = _make_client(get_responses={path: [_OCSF_EVENTS]})
    result = await audit_events_ocsf(
        cast(AutomoxClient, client),
        org_id=42,
        date="2026-03-25",
    )

    with_strings, ids_only = result["data"]["events"]
    # Upstream-provided strings are preserved verbatim.
    assert with_strings["severity"] == "Informational"
    assert with_strings["status"] == "Success"
    # Missing strings are derived from the OCSF integer enums.
    assert ids_only["severity"] == "informational"
    assert ids_only["status"] == "failure"
    assert ids_only["severity_id"] == 1
    assert ids_only["status_id"] == 2


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


# ---------------------------------------------------------------------------
# _ocsf_time_to_iso
# ---------------------------------------------------------------------------


def test_ocsf_time_non_numeric_passthrough() -> None:
    assert _ocsf_time_to_iso("2026-03-25T10:00:00Z") == "2026-03-25T10:00:00Z"
    assert _ocsf_time_to_iso(None) is None
    assert _ocsf_time_to_iso(True) is True  # bool is not a timestamp


def test_ocsf_time_defensive_milliseconds_branch() -> None:
    # Values too large to be seconds are treated as OCSF-standard millis.
    assert _ocsf_time_to_iso(1774432800123.0) == "2026-03-25T10:00:00.123000Z"


def test_ocsf_time_unconvertible_numeric_kept_verbatim() -> None:
    # Overflow in fromtimestamp must not raise — the raw value passes through.
    assert _ocsf_time_to_iso(float("inf")) == float("inf")
    # 9e10 is still valid seconds (year ~4821) and converts.
    assert isinstance(_ocsf_time_to_iso(9e10), str)
