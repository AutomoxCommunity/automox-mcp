"""Tests for human-readable tool titles (directory-submission requirement).

Every registered tool must expose a non-empty ``annotations.title`` so the
host client can render a human-readable name. Titles are derived from the
snake_case tool name by ``_apply_tool_titles`` as a post-registration pass.
"""

from __future__ import annotations

import pytest
from conftest import FakeClient
from fastmcp import FastMCP

import automox_mcp.tools as tools_mod
from automox_mcp.tools import _humanize_tool_name, register_tools


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("list_devices", "List Devices"),
        ("advanced_device_search", "Advanced Device Search"),
        ("audit_events_ocsf", "Audit Events OCSF"),
        ("get_device_by_uuid", "Get Device by UUID"),
        ("list_account_rbac_roles", "List Account RBAC Roles"),
        ("create_user_api_key", "Create User API Key"),
        ("policy_run_detail_v2", "Policy Run Detail v2"),
        ("assign_policies_to_saved_search", "Assign Policies to Saved Search"),
        ("remove_user_from_account", "Remove User from Account"),
        ("list_zones_for_user", "List Zones for User"),
        ("execute_policy_now", "Execute Policy Now"),
    ],
)
def test_humanize_tool_name(name: str, expected: str) -> None:
    assert _humanize_tool_name(name) == expected


def _build_full_server(monkeypatch: pytest.MonkeyPatch, *, remediation: bool = True) -> FastMCP:
    if remediation:
        monkeypatch.setenv("AUTOMOX_MCP_ALLOW_APPLY_REMEDIATION_ACTIONS", "true")
    server = FastMCP("test")
    register_tools(server, client=FakeClient())
    return server


def test_every_tool_has_a_title(monkeypatch: pytest.MonkeyPatch) -> None:
    server = _build_full_server(monkeypatch)
    lp = server.local_provider
    tools = {comp.name: comp for key, comp in lp._components.items() if key.startswith("tool:")}
    assert tools, "no tools registered"

    missing = [
        name
        for name, comp in tools.items()
        if comp.annotations is None or not comp.annotations.title
    ]
    assert missing == [], f"tools missing annotations.title: {missing}"


def test_title_does_not_clobber_other_annotation_hints(monkeypatch: pytest.MonkeyPatch) -> None:
    server = _build_full_server(monkeypatch)
    lp = server.local_provider
    tools = {comp.name: comp for key, comp in lp._components.items() if key.startswith("tool:")}

    # A read tool keeps readOnlyHint; a write tool keeps it false.
    assert tools["list_devices"].annotations.readOnlyHint is True
    assert tools["list_devices"].annotations.title == "List Devices"
    assert tools["delete_webhook"].annotations.readOnlyHint is False


def test_apply_titles_noop_on_stub_without_local_provider() -> None:
    """The pass must not raise on lightweight stubs lacking FastMCP internals."""

    class Bare:
        pass

    # Should return silently rather than AttributeError.
    tools_mod._apply_tool_titles(Bare())
