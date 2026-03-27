"""Tests for tool name prefixing (AUTOMOX_MCP_TOOL_PREFIX)."""

from __future__ import annotations

import os
from unittest.mock import patch

from automox_mcp.utils.tooling import get_tool_prefix


class TestGetToolPrefix:
    def test_default_empty(self):
        with patch.dict(os.environ, {}, clear=True):
            assert get_tool_prefix() == ""

    def test_returns_value(self):
        with patch.dict(os.environ, {"AUTOMOX_MCP_TOOL_PREFIX": "automox"}):
            assert get_tool_prefix() == "automox"

    def test_strips_whitespace(self):
        with patch.dict(os.environ, {"AUTOMOX_MCP_TOOL_PREFIX": "  ax  "}):
            assert get_tool_prefix() == "ax"


class TestApplyToolPrefix:
    def test_no_prefix_keeps_names(self):
        """When no prefix is set, tool names remain unchanged."""
        from fastmcp import FastMCP

        server = FastMCP("test")

        @server.tool(name="list_devices")
        def dummy() -> str:
            return "ok"

        # No prefix — names stay the same
        tm = server._tool_manager
        assert "list_devices" in tm._tools

    def test_prefix_renames_tools(self):
        """When prefix is set, all tool names get prefixed."""
        from fastmcp import FastMCP

        from automox_mcp.tools import _apply_tool_prefix

        server = FastMCP("test")

        @server.tool(name="list_devices")
        def dummy1() -> str:
            return "ok"

        @server.tool(name="policy_catalog")
        def dummy2() -> str:
            return "ok"

        _apply_tool_prefix(server, "automox")

        tm = server._tool_manager
        assert "automox_list_devices" in tm._tools
        assert "automox_policy_catalog" in tm._tools
        assert "list_devices" not in tm._tools
        assert "policy_catalog" not in tm._tools

    def test_prefixed_tool_name_attribute(self):
        """The tool object's .name attribute is also updated."""
        from fastmcp import FastMCP

        from automox_mcp.tools import _apply_tool_prefix

        server = FastMCP("test")

        @server.tool(name="test_tool")
        def dummy() -> str:
            return "ok"

        _apply_tool_prefix(server, "ax")

        tm = server._tool_manager
        tool = tm._tools["ax_test_tool"]
        assert tool.name == "ax_test_tool"
