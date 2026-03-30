"""Tests for new Phase 3 tool registration."""

from __future__ import annotations

import os
from unittest.mock import patch

from conftest import StubClient
from fastmcp import FastMCP


def _make_server_with_module(module_name: str, has_writes: bool = False) -> FastMCP:
    """Create a FastMCP server and register a single tool module."""
    import importlib

    server = FastMCP("test")
    client = StubClient()
    mod = importlib.import_module(f"automox_mcp.tools.{module_name}")
    mod.register(server, read_only=not has_writes, client=client)
    return server


def test_worklet_tools_register() -> None:
    server = _make_server_with_module("worklet_tools")
    tool_names = set(server._tool_manager._tools.keys())
    assert "search_worklet_catalog" in tool_names
    assert "get_worklet_detail" in tool_names


def test_data_extract_tools_register_read_only() -> None:
    server = _make_server_with_module("data_extract_tools", has_writes=False)
    tool_names = set(server._tool_manager._tools.keys())
    assert "list_data_extracts" in tool_names
    assert "get_data_extract" in tool_names
    assert "create_data_extract" not in tool_names


def test_data_extract_tools_register_with_writes() -> None:
    server = _make_server_with_module("data_extract_tools", has_writes=True)
    tool_names = set(server._tool_manager._tools.keys())
    assert "create_data_extract" in tool_names


def test_policy_history_tools_register() -> None:
    server = _make_server_with_module("policy_history_tools")
    tool_names = set(server._tool_manager._tools.keys())
    expected = {
        "policy_runs_v2",
        "policy_run_count",
        "policy_runs_by_policy",
        "policy_history_detail",
        "policy_runs_for_policy",
        "policy_run_detail_v2",
    }
    assert expected.issubset(tool_names)


def test_audit_v2_tools_register() -> None:
    server = _make_server_with_module("audit_v2_tools")
    tool_names = set(server._tool_manager._tools.keys())
    assert "audit_events_ocsf" in tool_names


def test_device_search_tools_register() -> None:
    server = _make_server_with_module("device_search_tools")
    tool_names = set(server._tool_manager._tools.keys())
    expected = {
        "list_saved_searches",
        "advanced_device_search",
        "device_search_typeahead",
        "get_device_metadata_fields",
        "get_device_assignments",
        "get_device_by_uuid",
    }
    assert expected.issubset(tool_names)


def test_vuln_sync_tools_register_read_only() -> None:
    server = _make_server_with_module("vuln_sync_tools", has_writes=False)
    tool_names = set(server._tool_manager._tools.keys())
    assert "list_remediation_action_sets" in tool_names
    assert "get_action_set_detail" in tool_names
    assert "upload_action_set" not in tool_names


def test_vuln_sync_tools_register_with_writes() -> None:
    server = _make_server_with_module("vuln_sync_tools", has_writes=True)
    tool_names = set(server._tool_manager._tools.keys())
    assert "upload_action_set" in tool_names


def test_account_tools_register_includes_api_keys() -> None:
    """Verify list_org_api_keys is registered even in read-only mode."""
    server = _make_server_with_module("account_tools", has_writes=False)
    tool_names = set(server._tool_manager._tools.keys())
    assert "list_org_api_keys" in tool_names


def test_valid_modules_includes_new_modules() -> None:
    from automox_mcp.utils.tooling import get_enabled_modules

    with patch.dict(
        os.environ,
        {
            "AUTOMOX_MCP_MODULES": (
                "worklets,data_extracts,vuln_sync,audit_v2,device_search,policy_history"
            )
        },
    ):
        enabled = get_enabled_modules()
    assert enabled == {
        "worklets",
        "data_extracts",
        "vuln_sync",
        "audit_v2",
        "device_search",
        "policy_history",
    }


def test_policy_windows_tools_register_read_only() -> None:
    server = _make_server_with_module("policy_windows_tools", has_writes=False)
    tool_names = set(server._tool_manager._tools.keys())
    read_tools = {
        "search_policy_windows",
        "get_policy_window",
        "check_group_exclusion_status",
        "check_window_active",
        "get_group_scheduled_windows",
        "get_device_scheduled_windows",
    }
    assert read_tools.issubset(tool_names)
    assert "create_policy_window" not in tool_names
    assert "update_policy_window" not in tool_names
    assert "delete_policy_window" not in tool_names


def test_policy_windows_tools_register_with_writes() -> None:
    server = _make_server_with_module("policy_windows_tools", has_writes=True)
    tool_names = set(server._tool_manager._tools.keys())
    assert "create_policy_window" in tool_names
    assert "update_policy_window" in tool_names
    assert "delete_policy_window" in tool_names


def test_valid_modules_includes_policy_windows() -> None:
    from automox_mcp.utils.tooling import get_enabled_modules

    with patch.dict(os.environ, {"AUTOMOX_MCP_MODULES": "policy_windows"}):
        enabled = get_enabled_modules()
    assert "policy_windows" in enabled


def test_unknown_modules_warned(caplog) -> None:
    import logging

    from automox_mcp.utils.tooling import get_enabled_modules

    with patch.dict(os.environ, {"AUTOMOX_MCP_MODULES": "worklets,fake_module"}):
        with caplog.at_level(logging.WARNING):
            enabled = get_enabled_modules()
    assert "worklets" in enabled
    assert "fake_module" in enabled  # unknown modules are still returned
    assert "fake_module" in caplog.text  # but a warning is logged
