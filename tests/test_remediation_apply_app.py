"""Tests for the remediation-apply review MCP App (issue #181, gated write-flow).

Server-side plumbing (CI has no live MCP host): the review UI resource lists with
the UI MIME and is self-contained; ``get_action_set_solutions`` carries the App
link and advertises its output_schema; the write it drives,
``apply_remediation_actions``, stays **Tier-2 env-gated** (registered only when
``AUTOMOX_MCP_ALLOW_APPLY_REMEDIATION_ACTIONS`` is set); and a conformance test
validates the entry tool's real output against its schema.
"""

from __future__ import annotations

from typing import Any, cast

import jsonschema
import pytest
from conftest import StubClient
from fastmcp import FastMCP
from fastmcp.tools import ToolResult

# Reuse the captured solutions fixture (real live-tenant shape).
from test_workflows_vuln_sync import _SOLUTIONS

from automox_mcp.client import AutomoxClient
from automox_mcp.resources.remediation_apply_app import REMEDIATION_APPLY_APP_URI
from automox_mcp.schemas import ActionSetSolutionsResult
from automox_mcp.tools.vuln_sync_tools import register as register_vuln
from automox_mcp.utils.tooling import as_tool_response, maybe_format_markdown
from automox_mcp.workflows.vuln_sync import get_action_set_solutions

UI_MIME = "text/html;profile=mcp-app"


def _server() -> FastMCP:
    srv = FastMCP("remediation-apply-test")
    register_vuln(srv, read_only=False, client=cast(AutomoxClient, StubClient()))
    from automox_mcp.resources import register_resources

    register_resources(srv, client=cast(AutomoxClient, StubClient()))
    return srv


def _by(srv: FastMCP, prefix: str) -> dict[str, Any]:
    lp = srv.local_provider
    if prefix == "resource:":
        return {str(c.uri): c for k, c in lp._components.items() if k.startswith(prefix)}
    return {c.name: c for k, c in lp._components.items() if k.startswith(prefix)}


def test_resource_registered_and_self_contained() -> None:
    res = _by(_server(), "resource:")
    assert REMEDIATION_APPLY_APP_URI in res
    assert res[REMEDIATION_APPLY_APP_URI].mime_type == UI_MIME
    html = res[REMEDIATION_APPLY_APP_URI].fn()
    assert html.lstrip().startswith("<!doctype html")
    assert "Remediation Apply Review" in html
    assert "window.AutomoxApp" in html
    assert "apply_remediation_actions" in html
    assert "patch-now" in html
    # patch-with-worklet is deliberately NOT offered in the UI.
    assert "patch-with-worklet" not in html
    # patch-now is gated on availability: only solutions whose remediation is a
    # direct patch get the button; worklet-based solutions get a note instead.
    assert "patchNowAvailable" in html
    assert "<script src" not in html and "https://" not in html


def test_entry_tool_links_app_and_advertises_schema() -> None:
    tool = _by(_server(), "tool:")["get_action_set_solutions"]
    assert tool.meta["ui"]["resourceUri"] == REMEDIATION_APPLY_APP_URI
    assert tool.output_schema == ActionSetSolutionsResult.model_json_schema()


def test_apply_tool_is_env_gated(monkeypatch: pytest.MonkeyPatch) -> None:
    """apply_remediation_actions is registered only when the env flag is set."""
    monkeypatch.delenv("AUTOMOX_MCP_ALLOW_APPLY_REMEDIATION_ACTIONS", raising=False)
    assert "apply_remediation_actions" not in _by(_server(), "tool:")
    monkeypatch.setenv("AUTOMOX_MCP_ALLOW_APPLY_REMEDIATION_ACTIONS", "true")
    assert "apply_remediation_actions" in _by(_server(), "tool:")


def test_output_schema_is_permissive() -> None:
    schema = ActionSetSolutionsResult.model_json_schema()
    assert not schema.get("required")

    def has_false(s: Any) -> bool:
        if isinstance(s, dict):
            return s.get("additionalProperties") is False or any(has_false(v) for v in s.values())
        if isinstance(s, list):
            return any(has_false(x) for x in s)
        return False

    assert not has_false(schema)
    jsonschema.validate(instance={}, schema=schema)


@pytest.mark.asyncio
async def test_solutions_output_conforms_json_and_markdown() -> None:
    client = StubClient(
        get_responses={"/orgs/42/remediations/action-sets/7/solutions": [_SOLUTIONS]}
    )
    result = await get_action_set_solutions(cast(AutomoxClient, client), org_id=42, action_set_id=7)
    schema = ActionSetSolutionsResult.model_json_schema()
    jsonschema.validate(instance=as_tool_response(result), schema=schema)

    md = maybe_format_markdown(as_tool_response(result), "markdown")
    assert isinstance(md, ToolResult)
    jsonschema.validate(instance=md.structured_content, schema=schema)
