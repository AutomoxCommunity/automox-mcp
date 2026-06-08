"""Tests for the read-only triage MCP App (issue #178).

These assert the server-side plumbing of the dependency-free MCP App: the
``ui://automox/triage.html`` resource lists with the UI MIME, and
``get_compliance_snapshot`` carries the ``AppConfig`` link in its tool meta —
introspected on a *real* ``FastMCP`` instance (the ``StubServer`` in
``conftest.py`` swallows ``meta``/``output_schema``). The App is purely additive:
the tool keeps its output_schema and behavior, and the other compound tools
carry no App link (graceful degradation on non-Apps hosts is the host's job; we
verify we did not alter the tool surface).
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from conftest import StubClient
from fastmcp import FastMCP

from automox_mcp.client import AutomoxClient
from automox_mcp.resources import register_resources
from automox_mcp.resources.triage_app import TRIAGE_APP_URI
from automox_mcp.tools.compound_tools import register as register_compound

UI_MIME = "text/html;profile=mcp-app"


@pytest.fixture
def server() -> FastMCP:
    srv = FastMCP("triage-app-test")
    register_compound(srv, read_only=False, client=cast(AutomoxClient, StubClient()))
    register_resources(srv, client=cast(AutomoxClient, StubClient()))
    return srv


def _resources(srv: FastMCP) -> dict[str, Any]:
    lp = srv.local_provider
    return {str(c.uri): c for key, c in lp._components.items() if key.startswith("resource:")}


def _tools(srv: FastMCP) -> dict[str, Any]:
    lp = srv.local_provider
    return {c.name: c for key, c in lp._components.items() if key.startswith("tool:")}


def test_triage_resource_registered_with_ui_mime(server: FastMCP) -> None:
    res = _resources(server)
    assert TRIAGE_APP_URI in res, f"{TRIAGE_APP_URI} not registered"
    assert res[TRIAGE_APP_URI].mime_type == UI_MIME


def test_triage_resource_serves_self_contained_html(server: FastMCP) -> None:
    resource = _resources(server)[TRIAGE_APP_URI]
    html = resource.fn()
    assert isinstance(html, str) and html.lstrip().startswith("<!doctype html")
    # The triage surface and the hand-rolled ext-apps bridge are present.
    assert "Compliance Triage" in html
    assert "ui/initialize" in html
    assert "ui/notifications/tool-result" in html
    assert "structuredContent" in html
    # Self-contained: no external script/style imports (would need CSP domains).
    assert "<script src" not in html
    assert "https://" not in html  # no CDN imports or external fetches


def test_compliance_snapshot_links_the_app(server: FastMCP) -> None:
    tool = _tools(server)["get_compliance_snapshot"]
    assert tool.meta is not None
    assert tool.meta["ui"]["resourceUri"] == TRIAGE_APP_URI


def test_app_is_additive_output_schema_preserved(server: FastMCP) -> None:
    """#176's output_schema must still be advertised alongside the App link."""
    tool = _tools(server)["get_compliance_snapshot"]
    assert tool.output_schema, "attaching the App dropped the output_schema"
    assert "data" in tool.output_schema.get("properties", {})


def test_other_compound_tools_have_no_app_link(server: FastMCP) -> None:
    """Only the triage entry tool carries the App; the others are unchanged."""
    tools = _tools(server)
    for name in ("get_patch_tuesday_readiness", "get_device_full_profile"):
        meta = tools[name].meta
        assert meta is None or "ui" not in meta, f"{name} unexpectedly carries an App link"


def test_triage_app_uri_constant_is_a_ui_scheme() -> None:
    assert TRIAGE_APP_URI.startswith("ui://")
