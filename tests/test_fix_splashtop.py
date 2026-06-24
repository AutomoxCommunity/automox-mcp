"""Regression tests for the Splashtop write-tool fixes.

Covers two confirmed bug classes:

1. UUID-in-body serialization (BUGS #4/#5/#6): the Splashtop install,
   initiate-connection, and bulk-set-attended-access params models type
   their device-UUID fields as ``uuid.UUID``. Dumped in python mode the
   workflow body carried raw ``uuid.UUID`` objects, which httpx's
   ``json.dumps`` cannot serialize (``TypeError``) — the three write tools
   were dead. The fix passes ``dump_mode="json"`` so the model emits string
   UUIDs. These tests drive each tool through the real
   ``call_tool_workflow`` path (the only path that constructs the typed
   model and reproduces the bug) and assert the captured request body is
   JSON-serializable with string UUID values.

2. Bare-string success body (BUG #9): Splashtop install/uninstall/
   force-disconnect return 2xx with an unquoted string body
   ('Command executed successfully'). ``_process_response`` called
   ``response.json()`` on it, raising and surfacing a successful write as
   ``AutomoxAPIError``. The fix returns ``{"message": response.text}`` for
   <400 non-JSON bodies while leaving >=400 error handling untouched.
"""

from __future__ import annotations

import json
from typing import Any, cast

import httpx
import pytest
from conftest import StubClient, StubServer

import automox_mcp.tools.splashtop_tools as splashtop_tools
from automox_mcp.client import AutomoxAPIError, AutomoxClient

_DEVICE_UUID = "550e8400-e29b-41d4-a716-446655440000"
_DEVICE_UUID_2 = "660e8400-e29b-41d4-a716-446655440001"


def _register_tools() -> tuple[StubServer, StubClient]:
    """Register the Splashtop write tools against a capturing stub client."""
    client = StubClient(
        post_responses={
            "/remotecontrol-st/install": ["Command executed successfully"],
            "/remotecontrol-st/initiate-connection": [{"splashtopUrl": "splashtop-sos://abc"}],
        },
        put_responses={"/remotecontrol-st/attended-access/bulk": [{}]},
    )
    server = StubServer()
    splashtop_tools.register(server, read_only=False, client=cast(AutomoxClient, client))
    return server, client


def _last_body(client: StubClient) -> Any:
    """Return the body (json_data) of the most recent recorded write call."""
    return client.calls[-1][2]


# ---------------------------------------------------------------------------
# BUGS #4/#5/#6 — UUID fields must serialize to strings in the request body
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_install_body_serializes_uuid_as_string() -> None:
    server, client = _register_tools()

    result = await server.tools["splashtop_install"](
        device_uuid=_DEVICE_UUID,
        os_family="windows",
    )

    body = _last_body(client)
    # Body must be JSON-encodable exactly as httpx would encode it — no TypeError.
    json.dumps(body)
    httpx.Request("POST", "http://x/", json=body)
    assert isinstance(body["device_uuid"], str)
    assert body["device_uuid"] == _DEVICE_UUID
    # Tool returned a result envelope (did not raise -> isError is False).
    assert isinstance(result, dict)
    assert result["data"]["queued"] is True


@pytest.mark.asyncio
async def test_initiate_connection_body_serializes_uuid_as_string() -> None:
    server, client = _register_tools()

    result = await server.tools["splashtop_initiate_connection"](
        device_uuid=_DEVICE_UUID,
        os_family="windows",
        connection_type="remote_control",
    )

    body = _last_body(client)
    json.dumps(body)
    httpx.Request("POST", "http://x/", json=body)
    # The initiate-connection endpoint keys the device UUID as ax_device_uuid.
    assert isinstance(body["ax_device_uuid"], str)
    assert body["ax_device_uuid"] == _DEVICE_UUID
    assert isinstance(result, dict)
    assert result["data"]["splashtopUrl"] == "splashtop-sos://abc"


@pytest.mark.asyncio
async def test_set_bulk_attended_access_body_serializes_uuids_as_strings() -> None:
    server, client = _register_tools()

    result = await server.tools["splashtop_set_bulk_attended_access"](
        device_uuids=[_DEVICE_UUID, _DEVICE_UUID_2],
        required_attended_access=True,
    )

    body = _last_body(client)
    json.dumps(body)
    httpx.Request("PUT", "http://x/", json=body)
    assert body["deviceUuids"] == [_DEVICE_UUID, _DEVICE_UUID_2]
    assert all(isinstance(u, str) for u in body["deviceUuids"])
    assert isinstance(result, dict)
    assert result["data"]["updated"] is True


# ---------------------------------------------------------------------------
# BUG #9 — bare-string success body is a success, not a parse error
# ---------------------------------------------------------------------------


def _process(response: httpx.Response, *, allow_text_response: bool = False) -> Any:
    """Run a response through the real client._process_response."""
    client = AutomoxClient(
        api_key="k",
        account_uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        org_id=1,
    )
    return client._process_response(
        response,
        method="POST",
        path="/x",
        correlation_id=None,
        start=0.0,
        allow_text_response=allow_text_response,
    )


def test_bare_string_success_body_returns_message_when_opted_in() -> None:
    response = httpx.Response(
        200,
        headers={"Content-Type": "application/json"},
        # Bare, unquoted string -> response.json() raises JSONDecodeError.
        content=b"Command executed successfully",
    )
    result = _process(response, allow_text_response=True)
    assert result == {"message": "Command executed successfully"}


def test_bare_string_success_body_still_raises_without_opt_in() -> None:
    """The global strict-JSON guard is preserved for every non-opted-in caller."""
    response = httpx.Response(
        200,
        headers={"Content-Type": "application/json"},
        content=b"Command executed successfully",
    )
    with pytest.raises(AutomoxAPIError, match="invalid JSON"):
        _process(response)


def test_empty_success_body_still_returns_empty_dict() -> None:
    response = httpx.Response(204, content=b"")
    assert _process(response, allow_text_response=True) == {}


def test_error_status_with_bare_string_body_still_raises() -> None:
    response = httpx.Response(
        500,
        headers={"Content-Type": "application/json"},
        content=b"Internal Server Error",
    )
    with pytest.raises(AutomoxAPIError) as excinfo:
        _process(response, allow_text_response=True)
    assert excinfo.value.status_code == 500
