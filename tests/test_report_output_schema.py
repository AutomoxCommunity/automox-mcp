"""Tests for the report tools' advertised ``output_schema`` (issue #177, phase 2).

Mirrors ``test_compound_output_schema.py`` for the two report tools, and adds the
phase-2 twist: these tools can return **markdown** via ``maybe_format_markdown``.
The refactored helper returns a ``ToolResult`` whose ``structured_content`` is the
unchanged envelope, so the same advertised object schema validates in *both* JSON
and markdown modes. We prove that with the same ``jsonschema`` the MCP SDK uses,
running real workflow output (reusing the captured fixtures from
``test_workflows_reports``).
"""

from __future__ import annotations

from typing import Any, cast

import jsonschema
import pytest
from conftest import StubClient
from fastmcp import FastMCP
from fastmcp.tools import ToolResult

# Reuse the captured/real report fixtures, not invented shapes.
from test_workflows_reports import _LIVE_PREPATCH_RESPONSE, _make_noncompliant_response

from automox_mcp.client import AutomoxClient
from automox_mcp.schemas import NoncompliantReportResult, PrepatchReportResult
from automox_mcp.utils.tooling import as_tool_response, maybe_format_markdown
from automox_mcp.workflows.reports import get_noncompliant_report, get_prepatch_report

_TOOL_TO_MODEL = {
    "prepatch_report": PrepatchReportResult,
    "noncompliant_report": NoncompliantReportResult,
}


def _registered_report_tools() -> dict[str, Any]:
    from automox_mcp.tools.report_tools import register

    server = FastMCP("report-schema-test")
    register(server, read_only=False, client=cast(AutomoxClient, StubClient()))
    lp = server.local_provider
    return {comp.name: comp for key, comp in lp._components.items() if key.startswith("tool:")}


def _has_additional_properties_false(schema: Any) -> bool:
    if isinstance(schema, dict):
        if schema.get("additionalProperties") is False:
            return True
        return any(_has_additional_properties_false(v) for v in schema.values())
    if isinstance(schema, list):
        return any(_has_additional_properties_false(item) for item in schema)
    return False


# ---------------------------------------------------------------------------
# Advertisement
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool_name", sorted(_TOOL_TO_MODEL))
def test_report_tool_advertises_model_output_schema(tool_name: str) -> None:
    tools = _registered_report_tools()
    assert tool_name in tools
    schema = tools[tool_name].output_schema
    assert schema == _TOOL_TO_MODEL[tool_name].model_json_schema()
    assert schema.get("type") == "object"
    assert "data" in schema.get("properties", {})


# ---------------------------------------------------------------------------
# Permissiveness guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model", sorted(_TOOL_TO_MODEL.values(), key=lambda m: m.__name__))
def test_report_schema_is_permissive(model: Any) -> None:
    schema = model.model_json_schema()
    assert not _has_additional_properties_false(schema), (
        f"{model.__name__} has additionalProperties:false"
    )
    assert not schema.get("required"), f"{model.__name__} declares required fields"
    jsonschema.validate(instance={}, schema=schema)


# ---------------------------------------------------------------------------
# Runtime non-rejection — JSON mode AND markdown mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prepatch_report_output_conforms_json_and_markdown() -> None:
    client = StubClient(get_responses={"/reports/prepatch": [_LIVE_PREPATCH_RESPONSE]})
    result = await get_prepatch_report(cast(AutomoxClient, client), org_id=42, limit=500)
    schema = PrepatchReportResult.model_json_schema()

    # JSON mode: the plain envelope FastMCP would wrap + validate.
    envelope = as_tool_response(result)
    jsonschema.validate(instance=envelope, schema=schema)

    # Markdown mode: ToolResult whose structured_content is the SAME envelope,
    # which FastMCP validates against this exact schema.
    md = maybe_format_markdown(envelope, "markdown")
    assert isinstance(md, ToolResult)
    jsonschema.validate(instance=md.structured_content, schema=schema)


@pytest.mark.asyncio
async def test_noncompliant_report_output_conforms_json_and_markdown() -> None:
    device = {
        "id": 101,
        "name": "web-01",
        "groupId": 10,
        "os_family": "Windows",
        "connected": True,
        "needsReboot": False,
        "lastRefreshTime": "2026-06-05T00:00:00Z",
        "policies": [
            {
                "id": 301,
                "name": "Weekday Patching",
                "type": "patch",
                "severity": "critical",
                "reasonForFail": "patch failed: timeout",
                "packages": [{"id": 1}, {"id": 2}],
            }
        ],
    }
    client = StubClient(
        get_responses={"/reports/needs-attention": [_make_noncompliant_response([device])]}
    )
    result = await get_noncompliant_report(cast(AutomoxClient, client), org_id=42, limit=500)
    schema = NoncompliantReportResult.model_json_schema()

    envelope = as_tool_response(result)
    jsonschema.validate(instance=envelope, schema=schema)

    md = maybe_format_markdown(envelope, "markdown")
    assert isinstance(md, ToolResult)
    jsonschema.validate(instance=md.structured_content, schema=schema)


@pytest.mark.asyncio
async def test_empty_reports_conform_to_schema() -> None:
    """Empty device lists (degraded/empty org) still validate."""
    pre_client = StubClient(
        get_responses={"/reports/prepatch": [{"prepatch": {"total": 0, "devices": []}}]}
    )
    pre = await get_prepatch_report(cast(AutomoxClient, pre_client), org_id=42, limit=500)
    jsonschema.validate(
        instance=as_tool_response(pre), schema=PrepatchReportResult.model_json_schema()
    )

    nc_client = StubClient(
        get_responses={"/reports/needs-attention": [{"nonCompliant": {"total": 0, "devices": []}}]}
    )
    nc = await get_noncompliant_report(cast(AutomoxClient, nc_client), org_id=42, limit=500)
    jsonschema.validate(
        instance=as_tool_response(nc), schema=NoncompliantReportResult.model_json_schema()
    )
