"""Tests for audit service v2 (OCSF) workflows."""

from typing import Any, cast

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.audit_v2 import _ocsf_time_to_iso, audit_events_ocsf

_ORG_UUID = "11111111-2222-3333-4444-555555555555"

_OCSF_EVENTS = [
    # Shapes are SANITIZED CAPTURES of the live audit-service payload (probed
    # 2026-06-05 against /audit-service/v1/orgs/{uuid}/events). Key live facts
    # pinned here, all of which the prior invented fixture got wrong:
    #   * Events carry NO `category_name` field — only an integer `category_uid`.
    #   * `category_uid` maps 1:N across categories: 3 covers BOTH Authentication
    #     and Entity Management; 6 is Web Resources Activity.
    #   * `type_name` is the only category string, prefixed with a human label
    #     and a colon+space boundary ("Authentication: Logoff", "Entity
    #     Management: Create", "Web Resources Activity: Delete").
    #   * `time` is epoch SECONDS as a float (not ISO, not OCSF-standard millis).
    #   * Authentication events nest the user under `actor.user`; Web Resources
    #     Activity events use a `web_resources` list (no `resource`/`object`).
    {
        # Authentication, category_uid=3 — live carried both `severity` and
        # `status` strings alongside the integer ids.
        "_id": "6a21c3d1106afe9d63dc377f",
        "metadata": {"uid": "1f160432-e38d-6d70-982b-d3c30f874c91", "version": "1.1.0"},
        "time": 1774432800.123456,  # 2026-03-25T10:00:00Z
        "category_uid": 3,
        "type_uid": 300202,
        "type_name": "Authentication: Logoff",
        "class_uid": 3002,
        "activity": "Log Off",
        "activity_id": 99,
        "message": "User Logged Out",
        "severity": "Informational",
        "severity_id": 1,
        "status": "Other",
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
        # Entity Management, ALSO category_uid=3 — pins the 1:N category_uid case
        # and that no category_name field exists. String labels omitted (live
        # events sometimes carry only the integer ids).
        "_id": "6a21c3d1106afe9d63dc3780",
        "metadata": {"uid": "1f160432-e38d-6d70-982b-d3c30f874c92", "version": "1.1.0"},
        "time": 1774436400.0,  # 2026-03-25T11:00:00Z
        "category_uid": 3,
        "type_uid": 300101,
        "type_name": "Entity Management: Create",
        "class_uid": 3001,
        "activity": "Create",
        "activity_id": 1,
        "message": "Policy created",
        "severity_id": 1,
        "status_id": 2,
    },
    {
        # Web Resources Activity, category_uid=6 — uses `web_resources`, not a
        # `resource`/`object` block.
        "_id": "6a22f358ac50433c641c2707",
        "metadata": {"uid": "1f160f81-12ee-6d40-9e85-36c7563f5753", "version": "1.1.0"},
        "time": 1774440000.0,  # 2026-03-25T12:00:00Z
        "category_uid": 6,
        "type_uid": 600104,
        "type_name": "Web Resources Activity: Delete",
        "class_uid": 6001,
        "activity": "Delete",
        "activity_id": 4,
        "message": "Delete Device",
        "severity": "Informational",
        "severity_id": 1,
        "status_id": 1,
        "web_resources": [
            {"uid": "1234567", "name": "device-host", "type": "Device"},
        ],
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

    assert result["data"]["events_returned"] == 3
    assert result["data"]["date"] == "2026-03-25"
    assert result["data"]["org_uuid"] == _ORG_UUID
    # Real payloads have NO category_name field; the projection must not invent
    # one. The events still come through (pins the no-phantom-field contract).
    assert all("category_name" not in e for e in result["data"]["events"])
    # The event identifier lives under `_id` + `metadata.uid` live — NOT a
    # top-level `uid` (which is always absent). The projection must surface both
    # real identifiers; reading a non-existent top-level `uid` yielded None.
    e0 = result["data"]["events"][0]
    assert e0["_id"] == "6a21c3d1106afe9d63dc377f"
    assert e0["uid"] == "1f160432-e38d-6d70-982b-d3c30f874c91"  # from metadata.uid


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
    assert events[2]["time"] == "2026-03-25T12:00:00Z"


@pytest.mark.asyncio
async def test_enum_labels_filled_when_upstream_omits_strings() -> None:
    path = f"/audit-service/v1/orgs/{_ORG_UUID}/events"
    client = _make_client(get_responses={path: [_OCSF_EVENTS]})
    result = await audit_events_ocsf(
        cast(AutomoxClient, client),
        org_id=42,
        date="2026-03-25",
    )

    with_strings = result["data"]["events"][0]  # Authentication, has strings
    ids_only = result["data"]["events"][1]  # Entity Management, ids only
    # Upstream-provided strings are preserved verbatim.
    assert with_strings["severity"] == "Informational"
    assert with_strings["status"] == "Other"
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
async def test_web_resources_activity_event_projected() -> None:
    path = f"/audit-service/v1/orgs/{_ORG_UUID}/events"
    client = _make_client(get_responses={path: [_OCSF_EVENTS]})
    result = await audit_events_ocsf(
        cast(AutomoxClient, client),
        org_id=42,
        date="2026-03-25",
    )

    # The live Web Resources Activity event (category_uid=6) is the third event
    # and is projected with its OCSF taxonomy fields and type_name. The upstream
    # uses a `web_resources` block (not `resource`/`object`/`device`), which the
    # current projection does not surface — assert the event itself comes
    # through with its identifying strings.
    web_event = result["data"]["events"][2]
    assert web_event["type_name"] == "Web Resources Activity: Delete"
    assert web_event["category_uid"] == 6
    assert web_event["activity"] == "Delete"


@pytest.mark.asyncio
async def test_category_filter_narrows_via_type_name_prefix() -> None:
    # The upstream has NO category_name field; category filtering must narrow on
    # the type_name prefix. 'authentication' -> only the "Authentication:" event.
    # This FAILS against the old code path that matched the absent category_name.
    path = f"/audit-service/v1/orgs/{_ORG_UUID}/events"
    client = _make_client(get_responses={path: [_OCSF_EVENTS]})
    result = await audit_events_ocsf(
        cast(AutomoxClient, client),
        org_id=42,
        date="2026-03-25",
        category_name="authentication",
    )

    assert result["data"]["events_returned"] == 1
    assert result["data"]["events"][0]["type_name"] == "Authentication: Logoff"
    # events_before_filter still reports the unfiltered count so an empty
    # filtered result is distinguishable from "no activity".
    assert result["metadata"]["events_before_filter"] == 3
    assert result["metadata"]["applied_filters"]["category_name_matched"] is True


@pytest.mark.asyncio
async def test_category_filter_entity_management_does_not_match_authentication() -> None:
    # Both Authentication and Entity Management share category_uid=3 live, so a
    # category_uid filter could not distinguish them — the type_name prefix can.
    path = f"/audit-service/v1/orgs/{_ORG_UUID}/events"
    client = _make_client(get_responses={path: [_OCSF_EVENTS]})
    result = await audit_events_ocsf(
        cast(AutomoxClient, client),
        org_id=42,
        date="2026-03-25",
        category_name="entity_management",
    )

    assert result["data"]["events_returned"] == 1
    assert result["data"]["events"][0]["type_name"] == "Entity Management: Create"


@pytest.mark.asyncio
async def test_unknown_category_token_does_not_zero_results() -> None:
    # An unmappable/underivable token must NOT silently zero the result (the
    # exact "empty looks like no activity" failure mode this fix removes). It
    # leaves the events unfiltered and flags category_name_matched=false.
    path = f"/audit-service/v1/orgs/{_ORG_UUID}/events"
    client = _make_client(get_responses={path: [_OCSF_EVENTS]})
    result = await audit_events_ocsf(
        cast(AutomoxClient, client),
        org_id=42,
        date="2026-03-25",
        category_name="not_a_real_category",
    )

    assert result["data"]["events_returned"] == 3
    assert result["metadata"]["applied_filters"]["category_name_matched"] is False
    assert result["metadata"]["events_before_filter"] == 3
    assert any("could not be mapped" in note for note in result["metadata"]["field_notes"])


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

    assert result["data"]["events_returned"] == 1


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

    assert result["data"]["events_returned"] == 3
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
    assert result["data"]["events_returned"] == 0


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
    assert result["data"]["events_returned"] == 1
    assert result["data"]["events"][0]["type_name"] == "Authentication: Logoff"


@pytest.mark.asyncio
async def test_unverified_prefix_labeled_in_field_notes() -> None:
    # account_change is a spec-derived (unverified-live) prefix; the legend must
    # say so rather than asserting it as a verified vocabulary. The fixture has
    # no account_change event, so it narrows to zero — but events_before_filter
    # keeps the empty result distinguishable from "no activity".
    path = f"/audit-service/v1/orgs/{_ORG_UUID}/events"
    client = _make_client(get_responses={path: [_OCSF_EVENTS]})
    result = await audit_events_ocsf(
        cast(AutomoxClient, client),
        org_id=42,
        date="2026-03-25",
        category_name="account_change",
    )
    assert result["data"]["events_returned"] == 0
    assert result["metadata"]["events_before_filter"] == 3
    assert result["metadata"]["applied_filters"]["category_name_matched"] is True
    notes = result["metadata"]["field_notes"]
    assert any("unverified live" in note for note in notes)
    # account_change has a spec example, so its provenance is "spec example",
    # NOT "inferred".
    assert any("spec example" in note for note in notes)
    assert not any("inferred" in note for note in notes)


@pytest.mark.asyncio
async def test_user_access_prefix_labeled_inferred_not_spec_derived() -> None:
    # The spec has NO "User Access:" example — the prefix is an inference, not
    # spec-derived. The legend provenance must say "inferred", distinct from the
    # spec-example provenance used for account_change.
    path = f"/audit-service/v1/orgs/{_ORG_UUID}/events"
    client = _make_client(get_responses={path: [_OCSF_EVENTS]})
    result = await audit_events_ocsf(
        cast(AutomoxClient, client),
        org_id=42,
        date="2026-03-25",
        category_name="user_access",
    )
    assert result["metadata"]["applied_filters"]["category_name_matched"] is True
    notes = result["metadata"]["field_notes"]
    assert any("inferred (no spec example)" in note for note in notes)


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
