"""Tests for the access-certification (RBAC) review MCP App (issue #182).

Read-first: the review UI resource lists with the UI MIME, is self-contained, and
**drives no write** (certification is an in-session acknowledgment; no gated change
is wired — see the module docstring for why). ``list_users`` carries the App link
and advertises its output_schema, validated against real workflow output.
"""

from __future__ import annotations

from typing import Any, cast

import jsonschema
import pytest
from conftest import StubClient
from fastmcp import FastMCP
from fastmcp.tools import ToolResult

from automox_mcp.client import AutomoxClient
from automox_mcp.resources.access_certification_app import ACCESS_CERTIFICATION_APP_URI
from automox_mcp.schemas import UsersListResult
from automox_mcp.tools.account_tools import register as register_account
from automox_mcp.utils.tooling import as_tool_response, maybe_format_markdown
from automox_mcp.workflows.account import list_users

UI_MIME = "text/html;profile=mcp-app"

_USERS = [
    {
        "id": 7,
        "firstname": "Ada",
        "lastname": "Lovelace",
        "email": "ada@example.com",
        "account_rbac_roles": [{"id": 1, "name": "Admin"}],
        "rbac_roles": ["full_access"],
        "tfa_type": "totp",
        "intercom_hmac": "SECRET-should-not-surface",
    },
    {
        "id": 8,
        "firstname": "Grace",
        "lastname": "Hopper",
        "email": "grace@example.com",
        "account_rbac_roles": [],
        "rbac_roles": [],
        "tfa_type": None,
    },
]


def _server() -> FastMCP:
    srv = FastMCP("access-cert-test")
    register_account(srv, read_only=False, client=cast(AutomoxClient, StubClient()))
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
    assert ACCESS_CERTIFICATION_APP_URI in res
    assert res[ACCESS_CERTIFICATION_APP_URI].mime_type == UI_MIME
    html = res[ACCESS_CERTIFICATION_APP_URI].fn()
    assert html.lstrip().startswith("<!doctype html")
    assert "Access Certification" in html
    assert "window.AutomoxApp" in html
    assert "Certify" in html and "Flag" in html
    assert "<script src" not in html and "https://" not in html


def test_app_is_read_first_no_write_driven() -> None:
    """The UI never drives a write: no App.callTool invocation, no write-tool name."""
    html = _by(_server(), "resource:")[ACCESS_CERTIFICATION_APP_URI].fn()
    assert "App.callTool(" not in html
    for write_tool in ("remove_user_from_account", "update_user", "invite_user_to_account"):
        assert write_tool not in html


def test_entry_tool_links_app_and_advertises_schema() -> None:
    tool = _by(_server(), "tool:")["list_users"]
    assert tool.meta["ui"]["resourceUri"] == ACCESS_CERTIFICATION_APP_URI
    assert tool.output_schema == UsersListResult.model_json_schema()


def test_output_schema_is_permissive() -> None:
    schema = UsersListResult.model_json_schema()
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
async def test_users_output_conforms_json_and_markdown() -> None:
    client = StubClient(get_responses={"/users": [_USERS]})
    result = await list_users(cast(AutomoxClient, client), org_id=42)
    schema = UsersListResult.model_json_schema()
    jsonschema.validate(instance=as_tool_response(result), schema=schema)

    md = maybe_format_markdown(as_tool_response(result), "markdown")
    assert isinstance(md, ToolResult)
    jsonschema.validate(instance=md.structured_content, schema=schema)
