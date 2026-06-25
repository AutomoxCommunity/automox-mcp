"""Regression tests for three confirmed bugs in tooling/policy response handling.

Covers:
- BUG #2 — ``format_as_markdown_table`` / ``maybe_format_markdown`` must not raise
  ``AttributeError`` on a list of scalar (string) rows.
- BUG #3 — ``as_tool_response`` (and the ``describe_policy_run_result`` path) must
  sanitize non-coercible upstream ``metadata.limit`` / ``total_count`` rather than
  raising an uncaught ``ValidationError``.
- BUG #7 — ``_apply_token_budget`` must never report a truncated response as
  complete and must not let sibling count fields overstate the surviving list.
"""

from __future__ import annotations

from typing import cast
from uuid import UUID

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxClient
from automox_mcp.utils.tooling import (
    _apply_token_budget,
    as_tool_response,
    format_as_markdown_table,
    maybe_format_markdown,
)
from automox_mcp.workflows.policy import describe_policy_run_result

ORG_UUID = UUID("11111111-1111-1111-1111-111111111111")
POLICY_UUID = UUID("22222222-2222-2222-2222-222222222222")
EXEC_TOKEN = UUID("33333333-3333-3333-3333-333333333333")


# ---------------------------------------------------------------------------
# BUG #2 — markdown rendering of scalar rows
# ---------------------------------------------------------------------------


def test_format_as_markdown_table_with_string_rows_does_not_raise():
    """A list of UUID/name strings renders as a single-column table."""
    table = format_as_markdown_table(["uuid-a", "uuid-b"])

    assert "uuid-a" in table
    assert "uuid-b" in table
    # Single-column header, not a crash.
    assert table.splitlines()[0] == "| value |"


def test_maybe_format_markdown_with_string_list_envelope_does_not_raise():
    """An envelope whose first non-empty list is strings must tabulate cleanly."""
    envelope = {"data": {"saved_searches": ["uuid-a", "uuid-b"]}, "metadata": {}}

    result = maybe_format_markdown(envelope, "markdown")

    # ToolResult: structured envelope preserved, markdown content rendered.
    assert result.structured_content == envelope
    rendered = "".join(getattr(block, "text", str(block)) for block in result.content)
    assert "uuid-a" in rendered
    assert "uuid-b" in rendered


# ---------------------------------------------------------------------------
# BUG #3 — non-coercible reserved pagination keys are sanitized, not fatal
# ---------------------------------------------------------------------------


def test_as_tool_response_coerces_non_int_reserved_keys():
    """metadata.limit='' / total_count non-int degrade to None (no ValidationError)."""
    result = as_tool_response({"data": [1, 2], "metadata": {"limit": "", "total_count": "lots"}})

    assert result["metadata"]["limit"] is None
    assert result["metadata"]["total_count"] is None


def test_as_tool_response_preserves_coercible_string_int():
    """A numeric string still coerces to its int value."""
    result = as_tool_response({"data": [1], "metadata": {"limit": "25", "total_count": "100"}})

    assert result["metadata"]["limit"] == 25
    assert result["metadata"]["total_count"] == 100


@pytest.mark.asyncio
async def test_describe_policy_run_result_with_garbage_metadata_is_sanitized():
    """Upstream metadata.limit='' must not crash the run-results -> tool-response path."""
    upstream = {
        "data": [
            {"server_name": "host-1", "result_status": "success", "exit_code": 0},
        ],
        "metadata": {"current_page": 0, "limit": "", "total_count": "n/a"},
    }
    client = StubClient(
        get_responses={
            f"/policy-history/policies/{POLICY_UUID}/{EXEC_TOKEN}": [upstream],
        }
    )

    workflow_result = await describe_policy_run_result(
        cast(AutomoxClient, client),
        org_uuid=ORG_UUID,
        policy_uuid=POLICY_UUID,
        exec_token=EXEC_TOKEN,
    )

    # The legacy top-level keys must be guarded to int-or-None upstream...
    assert workflow_result["metadata"]["limit"] is None
    assert workflow_result["metadata"]["total_count"] is None

    # ...and as_tool_response must not raise on the full envelope.
    response = as_tool_response(workflow_result)
    assert response["metadata"]["limit"] is None
    assert response["metadata"]["total_count"] is None


# ---------------------------------------------------------------------------
# BUG #7 — truncation must never be misreported as complete; counts honest
# ---------------------------------------------------------------------------


def _oversized_devices(n: int) -> list[dict[str, str]]:
    # Each row carries enough text to blow a tiny budget.
    return [{"name": f"device-{i}", "detail": "x" * 200} for i in range(n)]


def test_apply_token_budget_truncation_marks_has_more_true():
    """When items are dropped, a pagination block must not assert completeness."""
    devices = _oversized_devices(10)
    response = {
        "data": {"devices": devices, "total_devices": len(devices)},
        "metadata": {"pagination": {"has_more": False, "last": True}},
    }

    result = _apply_token_budget(response, budget=10)

    assert result["metadata"]["truncated"] is True
    pagination = result["metadata"]["pagination"]
    assert pagination["has_more"] is True
    assert pagination["last"] is False


def test_apply_token_budget_reconciles_sibling_counts():
    """No surviving total_*/_returned count may exceed the returned list length."""
    devices = _oversized_devices(10)
    response = {
        "data": {
            "devices": devices,
            "total_devices": len(devices),
            "devices_returned": len(devices),
            "device_count": len(devices),
        },
        "metadata": {"pagination": {"has_more": False}},
    }

    result = _apply_token_budget(response, budget=10)
    data = result["data"]
    returned = len(data["devices"])

    assert returned < 10  # truncation actually happened
    assert data["total_devices"] <= returned
    assert data["devices_returned"] <= returned
    assert data["device_count"] <= returned
    # And completeness is not claimed.
    assert result["metadata"]["pagination"]["has_more"] is True


def test_apply_token_budget_under_budget_is_untouched():
    """A response within budget passes through unchanged (no false truncation)."""
    response = {
        "data": {"devices": [{"name": "a"}], "total_devices": 1},
        "metadata": {"pagination": {"has_more": False}},
    }

    result = _apply_token_budget(response, budget=10_000)

    assert "truncated" not in result["metadata"]
    assert result["metadata"]["pagination"]["has_more"] is False
    assert result["data"]["total_devices"] == 1
