from datetime import date
from typing import Any, cast

import pytest

from automox_mcp.client import AutomoxAPIError, AutomoxClient
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


@pytest.mark.asyncio
async def test_audit_trail_filters_actor_and_resolves_org_uuid() -> None:
    resolved_uuid = "00000000-0000-0000-0000-000000000111"
    audit_path = f"/audit-service/v1/orgs/{resolved_uuid}/events"

    responses = {
        ("/orgs", "console"): [[{"id": 123, "uuid": resolved_uuid}]],
        (audit_path, "console"): [
            {
                "metadata": {"count": 2, "next": "https://example.test/next?cursor=cursor-3"},
                "data": [
                    {
                        "activity": "User Login",
                        "message": "User logged in",
                        "time": 1718213009419,
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
                        "activity": "Policy Change",
                        "message": "Policy updated",
                        "time": 1718214000000,
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
        ],
    }

    client = StubClient(responses, org_id=123)

    result = await audit_trail_user_activity(
        cast(AutomoxClient, client),
        org_id=123,
        date=date(2024, 9, 5),
        actor_email="alice@example.com",
        limit=100,
    )

    assert client.calls[0]["path"] == "/orgs"
    assert client.calls[1]["path"] == audit_path
    assert client.calls[1]["headers"]["x-ax-organization-uuid"] == resolved_uuid

    data = result["data"]
    metadata = result["metadata"]

    assert data["org_uuid"] == resolved_uuid
    assert data["events_returned"] == 1
    assert data["events"][0]["actor"]["email"] == "alice@example.com"
    assert metadata["events_seen"] == 2
    assert metadata["events_returned"] == 1
    assert metadata["next_cursor"] == "cursor-2"
    assert metadata["api_next_link"].endswith("cursor=cursor-3")
    assert metadata["applied_filters"]["actor_email"] == "alice@example.com"


@pytest.mark.asyncio
async def test_audit_trail_includes_sanitized_raw_event() -> None:
    org_uuid = "00000000-0000-0000-0000-000000000999"
    long_message = "A" * 900
    responses = {
        (f"/audit-service/v1/orgs/{org_uuid}/events", "console"): [
            {
                "metadata": {"count": 1},
                "data": [
                    {
                        "activity": "Policy Edited",
                        "message": long_message,
                        "time": 1718217424504,
                        "metadata": {"uid": "cursor-raw"},
                        "actor": {
                            "user": {
                                "user": {
                                    "email_addr": "alice@example.com",
                                    "uid": "11111111-1111-1111-1111-111111111111",
                                }
                            }
                        },
                        "resource": {"details": list(range(15))},
                    }
                ],
            }
        ],
    }
    client = StubClient(responses, org_id=999, org_uuid=org_uuid)

    result = await audit_trail_user_activity(
        cast(AutomoxClient, client),
        org_id=999,
        date=date(2024, 9, 6),
        actor_email=None,
        include_raw_events=True,
    )

    event = result["data"]["events"][0]
    assert event["timestamp"].endswith("Z")
    assert "raw_event" in event
    assert event["raw_event"]["message"].endswith("chars truncated)")
    assert event["raw_event"]["resource"]["details"][-1].startswith("... ")
    assert result["metadata"]["applied_filters"]["include_raw_events"] is True
    assert result["metadata"]["last_event_cursor"] == "cursor-raw"


@pytest.mark.asyncio
async def test_audit_trail_matches_email_from_observables() -> None:
    org_uuid = "00000000-0000-0000-0000-000000000555"
    audit_path = f"/audit-service/v1/orgs/{org_uuid}/events"

    responses = {
        (audit_path, "console"): [
            {
                "metadata": {"count": 1},
                "data": [
                    {
                        "activity": "API Key Created",
                        "message": "Key created",
                        "time": 1718217424504,
                        "metadata": {"uid": "cursor-observable"},
                        "observables": [
                            {"value": "henry@example.com", "type": "Email Address"},
                            {"value": "misc", "type": "Other"},
                        ],
                    }
                ],
            }
        ]
    }
    client = StubClient(responses, org_id=777, org_uuid=org_uuid)

    result = await audit_trail_user_activity(
        cast(AutomoxClient, client),
        org_id=777,
        date=date(2024, 9, 7),
        actor_email="henry@example.com",
    )

    assert result["data"]["events_returned"] == 1
    assert result["metadata"]["events_seen"] == 1


@pytest.mark.asyncio
async def test_audit_trail_resolves_actor_from_name_lookup() -> None:
    org_uuid = "00000000-0000-0000-0000-000000000222"
    account_uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    audit_path = f"/audit-service/v1/orgs/{org_uuid}/events"
    users_path = f"/accounts/{account_uuid}/users"

    responses = {
        ("/orgs", "console"): [[{"id": 44, "uuid": org_uuid}]],
        (users_path, "console"): [
            [
                {
                    "display_name": "Mark Hansen",
                    "email": "mark.hansen@example.com",
                    "uid": "33333333-3333-3333-3333-333333333333",
                    "account_rbac_role": "admin",
                },
                {
                    "display_name": "Marcy Hanson",
                    "email": "marcy.hanson@example.com",
                    "uid": "44444444-4444-4444-4444-444444444444",
                },
            ]
        ],
        (audit_path, "console"): [
            {
                "metadata": {"count": 2},
                "data": [
                    {
                        "activity": "Policy Updated",
                        "message": "Policy edited",
                        "time": 1718214000000,
                        "metadata": {"uid": "cursor-42"},
                        "actor": {
                            "user": {
                                "user": {
                                    "email_addr": "mark.hansen@example.com",
                                    "uid": "33333333-3333-3333-3333-333333333333",
                                }
                            }
                        },
                    },
                    {
                        "activity": "Task Created",
                        "message": "Another actor",
                        "time": 1718215000000,
                        "metadata": {"uid": "cursor-43"},
                        "actor": {
                            "user": {
                                "user": {
                                    "email_addr": "someone.else@example.com",
                                    "uid": "55555555-5555-5555-5555-555555555555",
                                }
                            }
                        },
                    },
                ],
            }
        ],
    }

    client = StubClient(
        responses,
        org_id=44,
        org_uuid=None,
        account_uuid=account_uuid,
    )

    result = await audit_trail_user_activity(
        cast(AutomoxClient, client),
        org_id=44,
        date=date(2024, 9, 8),
        actor_email=None,
        actor_name="Mark Hansen",
    )

    assert client.calls[0]["path"] == "/orgs"
    user_call = next((call for call in client.calls if call["path"] == users_path), None)
    assert user_call is not None
    assert user_call["params"]["search"] == "Mark Hansen"

    filters = result["metadata"]["applied_filters"]
    assert filters["actor_email"] == "mark.hansen@example.com"
    assert filters["actor_name"] == "Mark Hansen"
    assert result["metadata"]["actor_lookup"]["status"] == "matched"
    assert result["metadata"]["actor_lookup"]["resolved"]["email"] == "mark.hansen@example.com"
    assert result["metadata"]["actor_lookup"]["resolved"]["uuid"] == (
        "33333333-3333-3333-3333-333333333333"
    )

    assert result["data"]["events_returned"] == 1
    assert result["data"]["resolved_actor"]["name"] == "Mark Hansen"
    assert result["data"]["resolved_actor"]["email"] == "mark.hansen@example.com"


@pytest.mark.asyncio
async def test_audit_trail_handles_partial_email_hint() -> None:
    org_uuid = "00000000-0000-0000-0000-000000000333"
    account_uuid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    audit_path = f"/audit-service/v1/orgs/{org_uuid}/events"
    users_path = f"/accounts/{account_uuid}/users"

    responses = {
        (users_path, "console"): [
            [
                {
                    "display_name": "Mark Hansen",
                    "email": "mark.hansen@example.com",
                    "uid": "33333333-3333-3333-3333-333333333333",
                }
            ]
        ],
        (audit_path, "console"): [
            {
                "metadata": {"count": 1},
                "data": [
                    {
                        "activity": "Device Deleted",
                        "message": "Cleanup performed",
                        "time": 1718218000000,
                        "metadata": {"uid": "cursor-99"},
                        "actor": {
                            "user": {
                                "user": {
                                    "email_addr": "mark.hansen@example.com",
                                    "uid": "33333333-3333-3333-3333-333333333333",
                                }
                            }
                        },
                    }
                ],
            }
        ],
    }

    client = StubClient(
        responses,
        org_id=55,
        org_uuid=org_uuid,
        account_uuid=account_uuid,
    )

    result = await audit_trail_user_activity(
        cast(AutomoxClient, client),
        org_id=55,
        date=date(2024, 9, 9),
        actor_email="mark.hansen@",
    )

    filters = result["metadata"]["applied_filters"]
    assert filters["actor_email"] == "mark.hansen@example.com"
    assert filters["actor_email_hint"] == "mark.hansen@"
    lookup = result["metadata"]["actor_lookup"]
    assert lookup["status"] == "matched"
    assert lookup["partial_email_hint"] == "mark.hansen@"
    assert lookup["resolved"]["email"] == "mark.hansen@example.com"
    assert result["data"]["events_returned"] == 1


@pytest.mark.asyncio
async def test_audit_trail_lookup_handles_request_failure() -> None:
    org_uuid = "00000000-0000-0000-0000-000000000444"
    account_uuid = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    audit_path = f"/audit-service/v1/orgs/{org_uuid}/events"
    users_path = f"/accounts/{account_uuid}/users"

    responses = {
        (users_path, "console"): [
            AutomoxAPIError("Not found", status_code=404, payload={"errors": ["Not found"]})
        ],
        (audit_path, "console"): [
            {
                "metadata": {"count": 1},
                "data": [
                    {
                        "activity": "Policy Updated",
                        "message": "Policy edited",
                        "time": 1718219000000,
                        "metadata": {"uid": "cursor-404"},
                        "actor": {
                            "user": {
                                "user": {
                                    "email_addr": "mark.hansen@example.com",
                                    "uid": "33333333-3333-3333-3333-333333333333",
                                }
                            }
                        },
                    }
                ],
            }
        ],
    }

    client = StubClient(
        responses,
        org_id=77,
        org_uuid=org_uuid,
        account_uuid=account_uuid,
    )

    result = await audit_trail_user_activity(
        cast(AutomoxClient, client),
        org_id=77,
        date=date(2024, 9, 10),
        actor_name="Mark Hansen",
    )

    lookup = result["metadata"]["actor_lookup"]
    assert lookup["status"] == "error"
    assert lookup["reason"] == "actor_lookup_request_failed"
    assert lookup["error"]["status_code"] == 404
    assert lookup["error"]["payload"]["errors"] == ["Not found"]
    # Since lookup failed, we should not filter out events
    assert result["data"]["events_returned"] == 1
