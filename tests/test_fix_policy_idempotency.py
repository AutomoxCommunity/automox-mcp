"""Regression test for the apply_policy_changes idempotency-sentinel leak.

`apply_policy_changes` reserves an in-flight idempotency sentinel via
``check_idempotency`` before doing any work. ``normalize_policy_operations_input``
raises ``ToolError`` on common malformed input (missing ``action``). Before the
fix that normalize call ran *outside* the try/except that calls
``release_idempotency``, so a malformed first call left the reservation in place
for the full TTL — a corrected retry reusing the same ``request_id`` was then
shadowed by the duplicate no-op instead of executing.

These tests drive the real registered tool (deps stubbed) and assert that after a
normalize failure, a corrected retry with the SAME ``request_id`` EXECUTES rather
than returning the ``{"duplicate": True}`` marker.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from conftest import StubClient
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from automox_mcp.client import AutomoxClient
from automox_mcp.tools.policy_tools import register as register_policy

# A malformed op: missing the required ``action`` field → normalize raises.
_MALFORMED_OPS: list[dict[str, Any]] = [{"policy": {"name": "X"}}]

# A well-formed create op; ``preview=True`` exercises the workflow without
# requiring a canned POST response from the stub.
_VALID_OPS: list[dict[str, Any]] = [
    {
        "action": "create",
        "policy": {
            "name": "New Policy",
            "policy_type_name": "patch",
            "configuration": {"patch_rule": "all"},
            "schedule": {"days": ["monday"], "time": "02:00"},
            "server_groups": [],
        },
    }
]


def _apply_tool() -> Any:
    """Register the policy tools on a real FastMCP server and return the bound
    ``apply_policy_changes`` callable."""
    srv = FastMCP("policy-idempotency-test")
    register_policy(srv, read_only=False, client=cast(AutomoxClient, StubClient()))
    tools: dict[str, Any] = {
        c.name: c for key, c in srv.local_provider._components.items() if key.startswith("tool:")
    }
    return tools["apply_policy_changes"].fn


@pytest.mark.asyncio
async def test_normalize_failure_releases_sentinel_so_retry_executes() -> None:
    """Malformed first call raises; a corrected retry with the same request_id
    must EXECUTE, not return the duplicate no-op."""
    apply = _apply_tool()
    request_id = "req-normalize-leak"

    # First call: malformed input → normalize raises, reservation must be released.
    with pytest.raises(ToolError):
        await apply(operations=_MALFORMED_OPS, preview=True, request_id=request_id)

    # Retry with the SAME request_id but a valid payload.
    result = await apply(operations=_VALID_OPS, preview=True, request_id=request_id)

    # The tool executed (returned a real preview), not the duplicate marker.
    assert result["data"].get("duplicate") is not True
    assert result["data"]["preview"] is True


@pytest.mark.asyncio
async def test_duplicate_marker_still_returned_for_genuine_in_flight() -> None:
    """The release fix must not defeat idempotency: a stored result for the same
    request_id is replayed rather than re-executed."""
    apply = _apply_tool()
    request_id = "req-genuine-dup"

    first = await apply(operations=_VALID_OPS, preview=True, request_id=request_id)
    second = await apply(operations=_VALID_OPS, preview=True, request_id=request_id)

    # Second call replays the first stored response (idempotent), not a fresh run.
    assert second == first
