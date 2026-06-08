"""Tests for the policy change + blast-radius review MCP App (issue #180).

Server-side plumbing (CI has no live MCP host): the review UI resource lists with
the UI MIME and is self-contained; ``apply_policy_changes`` carries the App link
and advertises its output_schema; it remains gated (write mode only); and a
conformance check validates its real preview-mode output — plus the idempotency
duplicate marker — against the advertised schema.
"""

from __future__ import annotations

from typing import Any, cast

import jsonschema
import pytest
from conftest import StubClient
from fastmcp import FastMCP

from automox_mcp.client import AutomoxClient
from automox_mcp.resources.policy_blast_radius_app import POLICY_BLAST_RADIUS_APP_URI
from automox_mcp.schemas import PolicyChangeResult
from automox_mcp.tools.policy_tools import register as register_policy
from automox_mcp.utils.tooling import as_tool_response
from automox_mcp.workflows.policy_crud import apply_policy_changes

UI_MIME = "text/html;profile=mcp-app"


def _server(read_only: bool = False) -> FastMCP:
    srv = FastMCP("policy-blast-radius-test")
    register_policy(srv, read_only=read_only, client=cast(AutomoxClient, StubClient()))
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
    assert POLICY_BLAST_RADIUS_APP_URI in res
    assert res[POLICY_BLAST_RADIUS_APP_URI].mime_type == UI_MIME
    html = res[POLICY_BLAST_RADIUS_APP_URI].fn()
    assert html.lstrip().startswith("<!doctype html")
    assert "Policy Change Review" in html
    assert "window.AutomoxApp" in html and "App.onInput" in html
    # Re-invokes the write to apply, and resolves devices on demand.
    assert "apply_policy_changes" in html
    assert "preview_policy_device_filters" in html
    assert "<script src" not in html and "https://" not in html


def test_entry_tool_links_app_and_advertises_schema() -> None:
    tool = _by(_server(), "tool:")["apply_policy_changes"]
    assert tool.meta["ui"]["resourceUri"] == POLICY_BLAST_RADIUS_APP_URI
    assert tool.output_schema == PolicyChangeResult.model_json_schema()


def test_apply_tool_is_gated() -> None:
    """The App reuses the existing Tier-1 apply_policy_changes; absent in read-only."""
    assert "apply_policy_changes" in _by(_server(read_only=False), "tool:")
    assert "apply_policy_changes" not in _by(_server(read_only=True), "tool:")


def test_output_schema_is_permissive() -> None:
    schema = PolicyChangeResult.model_json_schema()
    assert not schema.get("required")

    def has_false(s: Any) -> bool:
        if isinstance(s, dict):
            return s.get("additionalProperties") is False or any(has_false(v) for v in s.values())
        if isinstance(s, list):
            return any(has_false(x) for x in s)
        return False

    assert not has_false(schema)
    jsonschema.validate(instance={}, schema=schema)
    # The idempotency duplicate-marker shape must also validate.
    jsonschema.validate(
        instance={"data": {"duplicate": True, "request_id": "abc"}, "metadata": {}},
        schema=schema,
    )


@pytest.mark.asyncio
async def test_preview_output_conforms_to_schema() -> None:
    """A real preview=True run validates against the advertised schema."""
    client = StubClient()
    client.org_id = 555  # type: ignore[attr-defined]
    result = await apply_policy_changes(
        cast(AutomoxClient, client),
        org_id=555,
        operations=[
            {
                "action": "create",
                "policy": {
                    "name": "New Policy",
                    "policy_type_name": "patch",
                    "configuration": {"patch_rule": "all"},
                    "schedule": {"days": ["monday"], "time": "02:00"},
                    "server_groups": [10, 11],
                },
            }
        ],
        preview=True,
    )
    assert result["data"]["preview"] is True
    jsonschema.validate(
        instance=as_tool_response(result), schema=PolicyChangeResult.model_json_schema()
    )
