"""Regression tests for BUG #11 — actor_name filter silently returning the whole
org event stream when the actor lookup cannot resolve.

When ``actor_name`` is provided but the lookup fails to resolve it to an email or
uuid, the client-side filter matches nothing. The pre-fix behaviour returned the
entire unfiltered org stream while ``applied_filters.actor_name`` still echoed the
requested name — every actor's events mislabeled as the requested actor's. The fix
returns zero events and surfaces ``metadata.filter_ineffective`` so the consumer can
tell the filter did not apply.
"""

from datetime import date
from typing import Any, cast

import pytest

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.audit import audit_trail_user_activity


class StubClient:
    def __init__(
        self,
        responses: dict[tuple[str, str], list[Any] | Any],
        *,
        org_id: int,
        org_uuid: str | None = None,
        account_uuid: str | None = None,
    ) -> None:
        self._responses = responses
        self.org_id = org_id
        self.org_uuid = org_uuid
        self.account_uuid = account_uuid
        self.calls: list[dict[str, Any]] = []

    async def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, Any] | None = None,
        api: str | None = None,
    ) -> Any:
        key = (path, api or "console")
        self.calls.append({"path": path, "params": params, "headers": headers, "api": api})
        if key not in self._responses:
            raise AssertionError(f"Unexpected GET request: {key!r}")
        response = self._responses[key]
        if isinstance(response, list):
            if not response:
                raise AssertionError(f"No stubbed responses remaining for {key!r}")
            item = response.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        if isinstance(response, Exception):
            raise response
        return response


def _two_actor_event_page() -> dict[str, Any]:
    """An org event page containing two different actors' events."""
    return {
        "metadata": {"count": 2},
        "data": [
            {
                "activity": "Policy Updated",
                "message": "Policy edited",
                "time": 1718214000000,
                "metadata": {"uid": "cursor-1"},
                "actor": {
                    "user": {
                        "user": {
                            "email_addr": "alice@example.com",
                            "uid": "11111111-1111-1111-1111-111111111111",
                        }
                    }
                },
            },
            {
                "activity": "Task Created",
                "message": "Different actor",
                "time": 1718215000000,
                "metadata": {"uid": "cursor-2"},
                "actor": {
                    "user": {
                        "user": {
                            "email_addr": "bob@example.com",
                            "uid": "22222222-2222-2222-2222-222222222222",
                        }
                    }
                },
            },
        ],
    }


@pytest.mark.asyncio
async def test_unresolved_actor_name_does_not_return_unfiltered_stream() -> None:
    """Case A: actor lookup yields no match for the requested actor_name.

    The response must NOT claim the events are that actor's filtered activity:
    ``applied_filters.actor_name`` is null, ``metadata.filter_ineffective`` is
    present, and no unrelated events are returned.
    """
    org_uuid = "00000000-0000-0000-0000-000000000333"
    account_uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    audit_path = f"/audit-service/v1/orgs/{org_uuid}/events"
    users_path = f"/accounts/{account_uuid}/users"

    responses = {
        ("/orgs", "console"): [[{"id": 44, "uuid": org_uuid}]],
        # Lookup returns no users matching the requested name.
        (users_path, "console"): [[]],
        (audit_path, "console"): [_two_actor_event_page()],
    }

    client = StubClient(responses, org_id=44, account_uuid=account_uuid)

    result = await audit_trail_user_activity(
        cast(AutomoxClient, client),
        org_id=44,
        date=date(2024, 9, 8),
        actor_name="Nobody Matches",
    )

    metadata = result["metadata"]
    data = result["data"]

    # The actor filter is NOT claimed as applied.
    assert metadata["applied_filters"]["actor_name"] is None
    assert metadata["applied_filters"]["actor_email"] is None
    assert metadata["applied_filters"]["actor_uuid"] is None

    # An honest, events-adjacent ineffective signal is present with a reason.
    ineffective = metadata["filter_ineffective"]
    assert ineffective["filter"] == "actor_name"
    assert ineffective["reason"] == "actor_name_unresolved"
    assert ineffective["requested_actor_name"] == "Nobody Matches"

    # The unrelated org-wide events are NOT presented as the actor's activity.
    assert data["events"] == []
    assert data["events_returned"] == 0
    assert metadata["events_returned"] == 0
    # The "no matches in a real filter, keep paginating" advice must NOT fire —
    # no filter was actually applied.
    assert "filter_pagination_state" not in metadata


@pytest.mark.asyncio
async def test_unresolved_actor_name_missing_account_uuid() -> None:
    """Case A variant: lookup is skipped because account_uuid is unavailable.

    Same honest signal — the filter is reported ineffective, not silently
    applied, and the org stream is not relabeled as the actor's.
    """
    org_uuid = "00000000-0000-0000-0000-000000000444"
    audit_path = f"/audit-service/v1/orgs/{org_uuid}/events"

    responses = {
        ("/orgs", "console"): [[{"id": 55, "uuid": org_uuid}]],
        (audit_path, "console"): [_two_actor_event_page()],
    }

    # account_uuid=None -> _lookup_actor_from_hints short-circuits as "skipped".
    client = StubClient(responses, org_id=55, account_uuid=None)

    result = await audit_trail_user_activity(
        cast(AutomoxClient, client),
        org_id=55,
        date=date(2024, 9, 8),
        actor_name="Alice Anderson",
    )

    metadata = result["metadata"]
    assert metadata["applied_filters"]["actor_name"] is None
    assert metadata["filter_ineffective"]["reason"] == "actor_name_unresolved"
    assert result["data"]["events"] == []
    assert result["data"]["events_returned"] == 0


@pytest.mark.asyncio
async def test_resolving_actor_name_still_filters_correctly() -> None:
    """Case B (regression): a resolving actor_name filters and is reported applied."""
    org_uuid = "00000000-0000-0000-0000-000000000555"
    account_uuid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    audit_path = f"/audit-service/v1/orgs/{org_uuid}/events"
    users_path = f"/accounts/{account_uuid}/users"

    responses = {
        ("/orgs", "console"): [[{"id": 66, "uuid": org_uuid}]],
        (users_path, "console"): [
            [
                {
                    "display_name": "Alice Anderson",
                    "email": "alice@example.com",
                    "uid": "11111111-1111-1111-1111-111111111111",
                    "account_rbac_role": "admin",
                }
            ]
        ],
        (audit_path, "console"): [_two_actor_event_page()],
    }

    client = StubClient(responses, org_id=66, account_uuid=account_uuid)

    result = await audit_trail_user_activity(
        cast(AutomoxClient, client),
        org_id=66,
        date=date(2024, 9, 8),
        actor_name="Alice Anderson",
    )

    metadata = result["metadata"]
    data = result["data"]

    # The resolved filter is honestly reported as applied.
    assert metadata["applied_filters"]["actor_name"] == "Alice Anderson"
    assert metadata["applied_filters"]["actor_email"] == "alice@example.com"
    # No ineffective signal when the filter resolved.
    assert "filter_ineffective" not in metadata

    # Only Alice's event survives the filter; Bob's is excluded.
    assert data["events_returned"] == 1
    assert data["events"][0]["actor"]["email"] == "alice@example.com"
