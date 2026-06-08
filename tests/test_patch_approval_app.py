"""Tests for the patch-approval review MCP App (issue #179, write-flow).

Server-side plumbing only (CI has no live MCP host, so the UI's actual
write-via-bridge is not exercised here): the review UI resource lists with the UI
MIME and is self-contained; ``patch_approvals_summary`` carries the App link and
advertises its output_schema; and the write it drives, ``decide_patch_approval``,
remains gated by the existing Tier-1 path (registered only in write mode). A
conformance test validates the entry tool's real output against its schema in
both JSON and markdown modes.
"""

from __future__ import annotations

from typing import Any, cast

import jsonschema
import pytest
from conftest import StubClient
from fastmcp import FastMCP
from fastmcp.tools import ToolResult

from automox_mcp.client import AutomoxClient
from automox_mcp.resources.patch_approval_app import PATCH_APPROVAL_APP_URI
from automox_mcp.schemas import PatchApprovalsSummaryResult
from automox_mcp.tools.policy_tools import register as register_policy
from automox_mcp.utils.tooling import as_tool_response, maybe_format_markdown
from automox_mcp.workflows.policy import summarize_patch_approvals

UI_MIME = "text/html;profile=mcp-app"


def _server(read_only: bool = False) -> FastMCP:
    srv = FastMCP("patch-approval-app-test")
    register_policy(srv, read_only=read_only, client=cast(AutomoxClient, StubClient()))
    # Resources register independently of the policy tools.
    from automox_mcp.resources import register_resources

    register_resources(srv, client=cast(AutomoxClient, StubClient()))
    return srv


def _components(srv: FastMCP, prefix: str) -> dict[str, Any]:
    lp = srv.local_provider
    if prefix == "resource:":
        return {str(c.uri): c for k, c in lp._components.items() if k.startswith(prefix)}
    return {c.name: c for k, c in lp._components.items() if k.startswith(prefix)}


def test_review_resource_registered_with_ui_mime() -> None:
    res = _components(_server(), "resource:")
    assert PATCH_APPROVAL_APP_URI in res
    assert res[PATCH_APPROVAL_APP_URI].mime_type == UI_MIME


def test_review_html_is_self_contained_and_drives_the_write_tool() -> None:
    html = _components(_server(), "resource:")[PATCH_APPROVAL_APP_URI].fn()
    assert html.lstrip().startswith("<!doctype html")
    assert "Patch Approval Review" in html
    # Uses the shared host bridge and the write path.
    assert "window.AutomoxApp" in html
    assert "tools/call" in html
    assert "decide_patch_approval" in html
    assert "Approve" in html and "Reject" in html
    # Self-contained: no external script/style imports (host default-deny CSP).
    assert "<script src" not in html
    assert "https://" not in html


def test_entry_tool_links_app_and_advertises_schema() -> None:
    tool = _components(_server(), "tool:")["patch_approvals_summary"]
    assert tool.meta["ui"]["resourceUri"] == PATCH_APPROVAL_APP_URI
    assert tool.output_schema == PatchApprovalsSummaryResult.model_json_schema()


def test_write_tool_is_gated_not_a_new_tool() -> None:
    """The App reuses the existing Tier-1 decide_patch_approval: present in write
    mode, absent in read-only mode (no new gate, no new write tool)."""
    write_tools = _components(_server(read_only=False), "tool:")
    ro_tools = _components(_server(read_only=True), "tool:")
    assert "decide_patch_approval" in write_tools
    assert "decide_patch_approval" not in ro_tools
    # The entry/review tool stays available in read-only mode (view-only).
    assert "patch_approvals_summary" in ro_tools


@pytest.mark.asyncio
async def test_patch_approvals_summary_output_conforms_json_and_markdown() -> None:
    envelope = {
        "size": 2,
        "results": [
            {
                "id": 401,
                "manual_approval": None,  # awaiting — the row the App renders
                "manual_approval_time": None,
                "status": "awaiting-unverified",
                "software": {
                    "display_name": "Chrome 120",
                    "version": "120.0.1",
                    "os_family": "Windows",
                    "severity": None,
                    "cves": ["CVE-2026-0001", "CVE-2026-0002"],
                },
                "policy": {"id": 5, "name": "Weekday Patching"},
            },
            {
                "id": 402,
                "manual_approval": True,
                "manual_approval_time": "2026-06-01 12:00:00",
                "status": "approved",
                "software": {"display_name": "Firefox 121", "severity": None, "cves": []},
                "policy": {"id": 5, "name": "Weekday Patching"},
            },
        ],
    }
    stub = StubClient(get_responses={"/approvals": [envelope]})
    stub.org_id = 42  # type: ignore[attr-defined]
    result = await summarize_patch_approvals(cast(AutomoxClient, stub), org_id=42)
    schema = PatchApprovalsSummaryResult.model_json_schema()

    jsonschema.validate(instance=as_tool_response(result), schema=schema)

    md = maybe_format_markdown(as_tool_response(result), "markdown")
    assert isinstance(md, ToolResult)
    jsonschema.validate(instance=md.structured_content, schema=schema)
