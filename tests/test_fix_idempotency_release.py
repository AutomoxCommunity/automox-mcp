"""Regression tests: write tools must release their idempotency reservation on
failure so a corrected retry (same ``request_id``) actually executes.

Bug pattern: a write tool reserves the sentinel
via ``check_idempotency`` then calls the workflow with no try/except that
releases the reservation on failure. Any failure leaves the slot reserved for
the full TTL, so the next retry with the same ``request_id`` is shadowed by the
in-flight "duplicate" no-op instead of running.

These tests exercise the REAL idempotency cache (conftest resets it per test).
Only the underlying workflow is stubbed — fail on the first call, succeed on the
retry — and we assert the retry routes through to the workflow (executes) and
returns the real result, not the ``{"duplicate": True}`` marker.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from conftest import FakeClient, StubServer
from fastmcp.exceptions import ToolError

from automox_mcp.tools import (
    account_tools,
    group_tools,
    policy_windows_tools,
    vuln_sync_tools,
)

_ACCT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_ORG_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _success() -> dict[str, Any]:
    return {"data": {"ok": True}, "metadata": {"deprecated_endpoint": False}}


# Each case wires up the fail-then-succeed workflow on the right target and
# returns the registered tool callable. Valid inputs mirror the existing
# dispatch tests / pydantic param models so only the forced failure (not a
# validation error) drives the first call.


def _wire_via_workflows_attr(
    module: Any, wf_name: str
) -> Callable[[pytest.MonkeyPatch, list[bool]], None]:
    """Tools that reference the workflow as ``module.workflows.<name>``."""

    def wire(monkeypatch: pytest.MonkeyPatch, calls: list[bool]) -> None:
        async def fail_then_succeed(client, **_):
            calls.append(True)
            if len(calls) == 1:
                raise RuntimeError("upstream blew up")
            return _success()

        monkeypatch.setattr(module.workflows, wf_name, fail_then_succeed)

    return wire


def _wire_via_module_alias(
    module: Any, alias: str
) -> Callable[[pytest.MonkeyPatch, list[bool]], None]:
    """Tools that reference the workflow via a module-level alias (vuln_sync)."""

    def wire(monkeypatch: pytest.MonkeyPatch, calls: list[bool]) -> None:
        async def fail_then_succeed(client, **_):
            calls.append(True)
            if len(calls) == 1:
                raise RuntimeError("upstream blew up")
            return _success()

        monkeypatch.setattr(module, alias, fail_then_succeed)

    return wire


# (tool_name, module, wiring, kwargs) — one row per fixed write tool.
_CASES = [
    # policy_windows
    (
        "create_policy_window",
        policy_windows_tools,
        _wire_via_workflows_attr(policy_windows_tools, "create_policy_window"),
        {
            "org_uuid": _ORG_UUID,
            "window_type": "exclude",
            "window_name": "win",
            "window_description": "desc",
            "rrule": "FREQ=DAILY;UNTIL=20271231T020000Z",
            "duration_minutes": 30,
            "use_local_tz": False,
            "recurrence": "once",
            "group_uuids": [_ORG_UUID],
            "dtstart": "2027-01-01T02:00:00Z",
            "status": "active",
        },
    ),
    (
        "update_policy_window",
        policy_windows_tools,
        _wire_via_workflows_attr(policy_windows_tools, "update_policy_window"),
        {
            "org_uuid": _ORG_UUID,
            "window_uuid": _ORG_UUID,
            "dtstart": "2027-01-01T02:00:00Z",
        },
    ),
    (
        "delete_policy_window",
        policy_windows_tools,
        _wire_via_workflows_attr(policy_windows_tools, "delete_policy_window"),
        {"org_uuid": _ORG_UUID, "window_uuid": _ORG_UUID},
    ),
    # group
    (
        "create_server_group",
        group_tools,
        _wire_via_workflows_attr(group_tools, "create_server_group"),
        {"name": "Prod", "refresh_interval": 360, "parent_server_group_id": 0},
    ),
    # account
    (
        "invite_user_to_account",
        account_tools,
        _wire_via_workflows_attr(account_tools, "invite_user_to_account"),
        {"email": "test@example.com", "account_rbac_role": "global-admin"},
    ),
    (
        "remove_user_from_account",
        account_tools,
        _wire_via_workflows_attr(account_tools, "remove_user_from_account"),
        {"user_id": _ACCT_UUID},
    ),
    # vuln_sync (workflow referenced via module-level alias)
    (
        "upload_action_set",
        vuln_sync_tools,
        _wire_via_module_alias(vuln_sync_tools, "_upload_action_set"),
        {"csv_content": "a,b\n1,2\n", "source": "generic", "filename": "x.csv"},
    ),
]

_CASE_IDS = [c[0] for c in _CASES]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name,module,wire,kwargs", _CASES, ids=_CASE_IDS)
async def test_failed_write_releases_sentinel_so_retry_executes(
    tool_name: str,
    module: Any,
    wire: Callable[[pytest.MonkeyPatch, list[bool]], None],
    kwargs: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First call fails; the SAME request_id retried with valid input must run
    the workflow again (execute) instead of returning the duplicate no-op.
    """
    monkeypatch.setenv("AUTOMOX_ACCOUNT_UUID", _ACCT_UUID)
    calls: list[bool] = []
    wire(monkeypatch, calls)

    server = StubServer()
    module.register(server, read_only=False, client=FakeClient(org_id=42))
    tool = server.tools[tool_name]

    # First call fails — the reservation must be released on the way out.
    # call_tool_workflow may surface the raw error or wrap it as ToolError.
    with pytest.raises((RuntimeError, ToolError)):
        await tool(request_id="retry-me", **kwargs)

    # Retry with the SAME request_id: must execute (not the duplicate marker).
    result = await tool(request_id="retry-me", **kwargs)

    # The retry executed: real result returned, NOT the duplicate no-op.
    assert result["data"] == {"ok": True}
    assert "duplicate" not in result.get("data", {})
    assert calls == [True, True]  # workflow ran on BOTH attempts


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name,module,wire,kwargs", _CASES, ids=_CASE_IDS)
async def test_unreleased_sentinel_would_shadow_retry_without_fix(
    tool_name: str,
    module: Any,
    wire: Callable[[pytest.MonkeyPatch, list[bool]], None],
    kwargs: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sanity-check the cache mechanics the fix relies on: a reservation left in
    place (no release) shadows a same-request_id retry with the duplicate
    marker. This is the failure the release fixes prevent.
    """
    from automox_mcp.utils.tooling import check_idempotency

    # Reserve the slot as the tool's first (failing) call would, but DON'T
    # release it — the pre-fix behaviour.
    first = await check_idempotency("shadow-me", tool_name)
    assert first is None  # fresh reservation

    monkeypatch.setenv("AUTOMOX_ACCOUNT_UUID", _ACCT_UUID)
    calls: list[bool] = []
    wire(monkeypatch, calls)

    server = StubServer()
    module.register(server, read_only=False, client=FakeClient(org_id=42))

    # Retry with the same request_id sees the in-flight sentinel → no execution.
    result = await server.tools[tool_name](request_id="shadow-me", **kwargs)
    assert result["data"]["duplicate"] is True
    assert calls == []  # workflow never ran — exactly the bug being fixed
