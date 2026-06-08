"""Tests for the compound tools' advertised ``output_schema`` (issue #176).

Two things are verified here that nothing else covers:

1. **Advertisement** — each compound tool registers a non-empty ``output_schema``
   equal to its Pydantic model's JSON schema. This must be introspected on a
   *real* ``FastMCP`` instance, because the ``StubServer`` in ``conftest.py``
   swallows ``**kwargs`` (including ``output_schema``).

2. **Runtime non-rejection** — FastMCP validates a tool's returned
   ``structured_content`` against the declared schema at runtime
   (``jsonschema.validate`` in the MCP SDK; a mismatch becomes ``isError=True``).
   So the schema must accept every real, mutated envelope the tool can emit. We
   prove this by running the actual workflows (with the same real fixtures
   ``test_workflows_compound`` uses), pushing the result through
   ``as_tool_response`` (the production envelope builder — token-budget
   truncation, ``correlation_id``, ``section_summaries``), and validating with
   the same ``jsonschema`` the SDK uses. A too-strict model would fail here
   instead of silently breaking the tool in production.
"""

from __future__ import annotations

from typing import Any, cast

import jsonschema
import pytest
from conftest import StubClient

# Reuse the *real* fixtures (not invented shapes) from the workflow tests.
from test_workflows_compound import (
    _build_compliance_client,
    _build_readiness_client,
    _patch_sub_workflows,
)

from automox_mcp.client import AutomoxClient
from automox_mcp.schemas import (
    ComplianceSnapshotResult,
    DeviceFullProfileResult,
    PatchTuesdayReadinessResult,
)
from automox_mcp.utils.tooling import as_tool_response
from automox_mcp.workflows.compound import (
    get_compliance_snapshot,
    get_device_full_profile,
    get_patch_tuesday_readiness,
)

_TOOL_TO_MODEL = {
    "get_compliance_snapshot": ComplianceSnapshotResult,
    "get_patch_tuesday_readiness": PatchTuesdayReadinessResult,
    "get_device_full_profile": DeviceFullProfileResult,
}


def _registered_compound_tools() -> dict[str, Any]:
    """Register compound tools on a REAL FastMCP and return {name: Tool}.

    StubServer discards ``output_schema``, so a real server is required to read
    it back — mirrors ``tools/__init__.py`` and ``test_doc_tool_counts.py``.
    """
    from fastmcp import FastMCP

    from automox_mcp.tools.compound_tools import register

    server = FastMCP("output-schema-test")
    register(server, read_only=False, client=cast(AutomoxClient, StubClient()))
    lp = server.local_provider
    return {comp.name: comp for key, comp in lp._components.items() if key.startswith("tool:")}


def _find_additional_properties_false(schema: Any) -> bool:
    """True if ``additionalProperties: false`` appears anywhere in the schema.

    That setting would turn the advertised schema into a hard runtime gate that
    rejects the extra metadata keys ``as_tool_response`` injects, so it must
    never appear in a compound-tool output schema.
    """
    if isinstance(schema, dict):
        if schema.get("additionalProperties") is False:
            return True
        return any(_find_additional_properties_false(v) for v in schema.values())
    if isinstance(schema, list):
        return any(_find_additional_properties_false(item) for item in schema)
    return False


# ---------------------------------------------------------------------------
# 1. Advertisement: each tool exposes its model's schema
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool_name", sorted(_TOOL_TO_MODEL))
def test_compound_tool_advertises_model_output_schema(tool_name: str) -> None:
    tools = _registered_compound_tools()
    assert tool_name in tools, f"{tool_name} not registered"
    schema = tools[tool_name].output_schema
    assert schema, f"{tool_name} has no output_schema"
    assert schema == _TOOL_TO_MODEL[tool_name].model_json_schema()
    # Top-level envelope is documented.
    assert schema.get("type") == "object"
    assert "data" in schema.get("properties", {})
    assert "metadata" in schema.get("properties", {})


# ---------------------------------------------------------------------------
# 2. Permissiveness guard: the schema must never gate a real response
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model", sorted(_TOOL_TO_MODEL.values(), key=lambda m: m.__name__))
def test_output_schema_has_no_additional_properties_false(model: Any) -> None:
    """Regression guard: nobody may tighten these models with extra='forbid'."""
    schema = model.model_json_schema()
    assert not _find_additional_properties_false(schema), (
        f"{model.__name__} schema contains additionalProperties:false — this gates "
        "the runtime payload and will break the tool. Keep these models extra='allow'."
    )
    # No required fields → degraded/subset returns validate.
    assert not schema.get("required"), f"{model.__name__} declares required fields"


@pytest.mark.parametrize("model", sorted(_TOOL_TO_MODEL.values(), key=lambda m: m.__name__))
def test_output_schema_accepts_empty_and_maximal_envelopes(model: Any) -> None:
    """Empty and fully-loaded (every metadata mutation) envelopes both validate."""
    schema = model.model_json_schema()
    # Empty — e.g. an early degraded return.
    jsonschema.validate(instance={}, schema=schema)
    # Maximal metadata: every key as_tool_response / token-budget can inject.
    maximal = {
        "data": {"some_unexpected_section": {"nested": [1, 2, 3]}},
        "metadata": {
            "current_page": None,
            "total_pages": None,
            "total_count": None,
            "limit": None,
            "previous": None,
            "next": None,
            "deprecated_endpoint": False,
            "correlation_id": "abc-123",
            "errors": ["device_inventory: AutomoxAPIError: 404"],
            "detail_limit": 10,
            "section_summaries": {"x": {"total": 30, "returned": 10, "has_more": True}},
            "notes": ["call `foo` for the rest"],
            "counts": {"packages_total": 50},
            "section_status": {"device_detail": "complete"},
            "data_complete": False,
            "truncated": True,
            "truncations": {"devices": {"total": 30, "returned": 15}},
            "estimated_tokens": 9001,
            "token_warning": "Response is ~9001 tokens (budget: 4000).",
        },
        "an_extra_top_level_key": True,
    }
    jsonschema.validate(instance=maximal, schema=schema)


# ---------------------------------------------------------------------------
# 3. Runtime non-rejection: real workflow output validates against the schema
# ---------------------------------------------------------------------------


def _validate(result: dict[str, Any], model: Any) -> None:
    """Push a workflow result through the production envelope builder and validate
    the emitted structured_content exactly as the MCP SDK would at runtime."""
    envelope = as_tool_response(result)
    jsonschema.validate(instance=envelope, schema=model.model_json_schema())


@pytest.mark.asyncio
async def test_compliance_snapshot_output_conforms_to_schema() -> None:
    client = _build_compliance_client()
    result = await get_compliance_snapshot(cast(AutomoxClient, client), org_id=555)
    _validate(result, ComplianceSnapshotResult)


@pytest.mark.asyncio
async def test_compliance_snapshot_truncated_output_conforms_to_schema() -> None:
    """The section_summaries / notes metadata path also validates."""
    noncompliant = {
        "nonCompliant": {
            "total": 30,
            "devices": [{"id": i, "name": f"nc-{i}", "groupId": 10} for i in range(30)],
        }
    }
    servers = [
        {
            "id": 1000 + i,
            "managed": True,
            "status": {"policy_status": "success"},
            "last_check_in": "2024-01-01T00:00:00Z",
        }
        for i in range(30)
    ]
    client = StubClient(
        get_responses={
            "/reports/needs-attention": [noncompliant],
            "/servers": [servers],
            "/policies": [[]],
            "/policystats": [[]],
        }
    )
    client.org_id = 555
    result = await get_compliance_snapshot(cast(AutomoxClient, client), org_id=555, detail_limit=10)
    assert result["metadata"]["section_summaries"]  # truncation path exercised
    _validate(result, ComplianceSnapshotResult)


@pytest.mark.asyncio
async def test_compliance_snapshot_empty_org_output_conforms_to_schema() -> None:
    client = StubClient(
        get_responses={
            "/reports/needs-attention": [{"nonCompliant": {"total": 0, "devices": []}}],
            "/servers": [[]],
            "/policies": [[]],
            "/policystats": [[]],
        }
    )
    client.org_id = 555
    result = await get_compliance_snapshot(cast(AutomoxClient, client), org_id=555)
    _validate(result, ComplianceSnapshotResult)


@pytest.mark.asyncio
async def test_patch_tuesday_readiness_output_conforms_to_schema() -> None:
    client = _build_readiness_client()
    result = await get_patch_tuesday_readiness(
        cast(AutomoxClient, client),
        org_id=555,
        org_uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    )
    _validate(result, PatchTuesdayReadinessResult)


@pytest.mark.asyncio
async def test_patch_tuesday_readiness_truncated_output_conforms_to_schema() -> None:
    devices = {
        "prepatch": {
            "devices": [
                {"id": i, "name": f"h-{i}", "patches": [{"severity": "high"}]} for i in range(30)
            ],
            "total": 30,
        }
    }
    approvals = {
        "size": 30,
        "results": [
            {"id": i, "status": "awaiting", "manual_approval": None, "software": {}, "policy": {}}
            for i in range(30)
        ],
    }
    policies = [
        {
            "id": 1000 + i,
            "name": f"P{i}",
            "policy_type_name": "patch",
            "status": "active",
            "schedule_days": 124,
            "schedule_time": "02:00",
        }
        for i in range(30)
    ]
    client = StubClient(
        get_responses={
            "/reports/prepatch": [devices],
            "/approvals": [approvals],
            "/policies": [policies],
            "/policystats": [[]],
        }
    )
    client.org_id = 555
    result = await get_patch_tuesday_readiness(
        cast(AutomoxClient, client),
        org_id=555,
        org_uuid="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        detail_limit=10,
    )
    assert result["metadata"]["section_summaries"]
    _validate(result, PatchTuesdayReadinessResult)


@pytest.mark.asyncio
async def test_device_full_profile_output_conforms_to_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_sub_workflows(monkeypatch)
    result = await get_device_full_profile(
        cast(AutomoxClient, StubClient()), org_id=555, device_id=101
    )
    _validate(result, DeviceFullProfileResult)


@pytest.mark.asyncio
async def test_device_full_profile_all_sections_fail_output_conforms_to_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fully degraded (all sub-workflows fail) still validates."""
    from unittest.mock import AsyncMock

    from automox_mcp.client import AutomoxAPIError

    _patch_sub_workflows(
        monkeypatch,
        describe_device=AsyncMock(side_effect=AutomoxAPIError("Forbidden", status_code=403)),
        get_device_inventory=AsyncMock(side_effect=AutomoxAPIError("Forbidden", status_code=403)),
        list_device_packages=AsyncMock(side_effect=AutomoxAPIError("Forbidden", status_code=403)),
    )
    result = await get_device_full_profile(
        cast(AutomoxClient, StubClient()), org_id=555, device_id=101
    )
    _validate(result, DeviceFullProfileResult)
