"""Pagination-honesty fixes for the policy workflows.

Covers three corrections in ``automox_mcp.workflows.policy``:

1. ``summarize_policies`` (policy_catalog) no longer sources its pagination
   totals from ``/policystats`` — that endpoint returns all policies (active
   and inactive), which overcounts an ``include_inactive=false`` page and makes
   ``has_more`` / ``total_pages`` claim more pages than the filtered set holds.
   The catalog now reports no fabricated grand total (the bare ``/policies``
   list supplies none) and ``policy_stats`` is an opt-in compliance payload.
2. ``summarize_patch_approvals`` names the per-page count ``approvals_returned``
   and reads the envelope ``size`` for the real grand total, adding ``has_more``
   and a ``suggested_next_call``.
3. ``describe_policy_run_result`` (policy_run_results) emits a
   ``suggested_next_call`` whenever ``has_more`` is true.

Stubs mirror the captured live shapes: ``/policies`` is a bare array,
``/policystats`` is a bare array of per-policy stat rows, ``/approvals`` is a
``{"size": N, "results": [...]}`` envelope, and the policy-history detail
endpoint returns ``{"metadata": {...}, "data": [...]}``.
"""

import copy
from typing import Any, cast
from uuid import UUID

import pytest

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.policy import (
    describe_policy_run_result,
    summarize_patch_approvals,
    summarize_policies,
)


class StubClient:
    """Minimal Automox client stub; records calls, replays canned responses."""

    def __init__(self, *, get_responses: dict[str, list[Any]] | None = None) -> None:
        self._get_responses = {key: list(value) for key, value in (get_responses or {}).items()}
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        self.org_id: int | None = None

    async def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        self.calls.append((path, params))
        responses = self._get_responses.get(path)
        if not responses:
            raise AssertionError(f"Unexpected GET request: {path}")
        return copy.deepcopy(responses.pop(0))


# ---------------------------------------------------------------------------
# Fix 1: policy_catalog totals reflect the include_inactive-filtered page,
#        not the all-policies /policystats payload.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_catalog_totals_not_sourced_from_policystats() -> None:
    """With include_inactive=false, the returned page drops inactive rows.
    /policystats (which counts ALL policies, active + inactive) must not drive
    the pagination total — it would overcount the returned population and make
    has_more / total_pages claim more pages than the filtered set holds.
    """
    active = {"id": 1, "name": "Active", "policy_type_name": "patch", "status": "active"}
    inactive = {"id": 2, "name": "Inactive", "policy_type_name": "patch", "status": "inactive"}
    # /policystats reports a far larger population than the filtered page.
    stats = [{"policy_id": i, "policy_name": f"P{i}"} for i in range(1, 51)]

    stub = StubClient(
        get_responses={
            "/policies": [[active, inactive]],
            "/policystats": [stats],
        }
    )
    stub.org_id = 42

    result = await summarize_policies(
        cast(AutomoxClient, stub),
        org_id=42,
        limit=20,
        include_inactive=False,
        include_stats=True,
    )

    data = result["data"]
    pagination = result["metadata"]["pagination"]

    # Only the active policy survived the filter; the inactive one is dropped.
    assert data["policies_returned"] == 1
    assert data["total_policies_considered"] == 1

    # The 50-row /policystats population must NOT leak into the totals.
    assert "total_policies_available" not in data
    assert "total_elements" not in pagination
    assert "total_pages" not in pagination
    assert result["metadata"].get("total_policies_available") is None

    # has_more reflects page fullness (2 raw rows < limit 20 => last page),
    # not an overcounted stats total.
    assert pagination["has_more"] is False
    assert "suggested_next_call" not in result["metadata"]

    # policy_stats remains available as the opt-in compliance payload.
    assert data["policy_stats"] == stats


@pytest.mark.asyncio
async def test_catalog_has_more_from_full_page_without_stats_total() -> None:
    """A full page (raw rows == limit) implies more may follow; the cursor and
    suggested_next_call derive from page fullness, never from a stats total.
    """
    policies = [
        {"id": i, "name": f"P{i}", "policy_type_name": "patch", "status": "active"}
        for i in range(3)
    ]
    stub = StubClient(get_responses={"/policies": [policies]})
    stub.org_id = 42

    result = await summarize_policies(
        cast(AutomoxClient, stub),
        org_id=42,
        limit=3,
        page=0,
        include_inactive=False,
        include_stats=False,
    )

    pagination = result["metadata"]["pagination"]
    assert pagination["has_more"] is True
    # No fabricated grand total when upstream supplies none.
    assert "total_elements" not in pagination
    next_call = result["metadata"]["suggested_next_call"]
    assert next_call["tool"] == "policy_catalog"
    assert next_call["args"]["page"] == 1
    # include_stats was not fetched (opt-in only).
    assert not any(path == "/policystats" for path, _ in stub.calls)


# ---------------------------------------------------------------------------
# Fix 2: summarize_patch_approvals uses approvals_returned + a real total
#        from the envelope `size`, and emits has_more + suggested_next_call.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approvals_returned_and_real_total_from_envelope_size() -> None:
    """The per-page count is named approvals_returned; the envelope `size` is
    the authoritative grand total. When size exceeds the page, has_more is true
    and a suggested_next_call advances the window.
    """
    envelope = {
        "size": 40,
        "results": [
            {
                "id": 1,
                "manual_approval": None,
                "status": "pending",
                "software": {"display_name": "App A", "severity": "Critical", "cves": []},
            },
            {
                "id": 2,
                "manual_approval": True,
                "status": "approved",
                "software": {"display_name": "App B", "severity": None, "cves": []},
            },
        ],
    }
    stub = StubClient(get_responses={"/approvals": [envelope]})
    stub.org_id = 42

    result = await summarize_patch_approvals(cast(AutomoxClient, stub), org_id=42, limit=2)
    data = result["data"]
    metadata = result["metadata"]

    # Per-page count under the new name; breakdowns tally only the page.
    assert data["approvals_returned"] == 2
    # Real grand total from the envelope `size`.
    assert data["total_approvals_available"] == 40
    assert metadata["total_approvals_available"] == 40
    # Deprecated alias preserved for non-owned consumers (App UI / schema).
    assert data["total_approvals_considered"] == 2

    # More of the queue remains than this page returned.
    assert metadata["has_more"] is True
    next_call = metadata["suggested_next_call"]
    assert next_call["tool"] == "patch_approvals_summary"
    # Window advances past the rows already returned.
    assert next_call["args"]["limit"] == 4


@pytest.mark.asyncio
async def test_approvals_no_has_more_when_size_within_page() -> None:
    """When the envelope `size` equals the returned page, the queue is fully
    covered: has_more is false and no suggested_next_call is emitted.
    """
    envelope = {
        "size": 1,
        "results": [
            {
                "id": 1,
                "manual_approval": None,
                "status": "pending",
                "software": {"display_name": "Only", "severity": None, "cves": []},
            }
        ],
    }
    stub = StubClient(get_responses={"/approvals": [envelope]})
    stub.org_id = 42

    result = await summarize_patch_approvals(cast(AutomoxClient, stub), org_id=42, limit=25)
    assert result["data"]["approvals_returned"] == 1
    assert result["data"]["total_approvals_available"] == 1
    assert result["metadata"]["has_more"] is False
    assert "suggested_next_call" not in result["metadata"]


@pytest.mark.asyncio
async def test_approvals_no_total_without_envelope_size() -> None:
    """A bare-list response carries no `size`; no grand total is fabricated and
    has_more is false.
    """
    stub = StubClient(get_responses={"/approvals": [[{"id": 1, "status": "pending"}]]})
    stub.org_id = 42

    result = await summarize_patch_approvals(cast(AutomoxClient, stub), org_id=42)
    data = result["data"]
    assert data["approvals_returned"] == 1
    assert "total_approvals_available" not in data
    assert result["metadata"]["has_more"] is False
    assert "suggested_next_call" not in result["metadata"]


# ---------------------------------------------------------------------------
# Fix 3: policy_run_results emits suggested_next_call alongside has_more.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_results_suggested_next_call_when_has_more() -> None:
    """When upstream pagination indicates another page, the wrapper hands back
    the exact next invocation (next page, same exec token / policy / filters).
    """
    org_uuid = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    policy_uuid = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    exec_token = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
    api_path = f"/policy-history/policies/{policy_uuid}/{exec_token}"
    payload = {
        # page 0 of 3 (50 total, 25 per page) => has_more is true.
        "metadata": {"current_page": 0, "total_pages": 3, "total_count": 50, "limit": 25},
        "data": [
            {"device_id": 1, "result_status": "success"},
            {"device_id": 2, "result_status": "failed"},
        ],
    }
    stub = StubClient(get_responses={api_path: [payload]})

    result = await describe_policy_run_result(
        cast(AutomoxClient, stub),
        org_uuid=org_uuid,
        policy_uuid=policy_uuid,
        exec_token=exec_token,
        page=0,
        limit=25,
    )

    metadata = result["metadata"]
    assert metadata["pagination"]["has_more"] is True
    next_call = metadata["suggested_next_call"]
    assert next_call["tool"] == "policy_run_results"
    args = next_call["args"]
    assert args["page"] == 1
    assert args["policy_uuid"] == str(policy_uuid)
    assert args["exec_token"] == str(exec_token)
    assert args["limit"] == 25


@pytest.mark.asyncio
async def test_run_results_no_suggested_next_call_on_last_page() -> None:
    """On the final page (has_more false), no suggested_next_call is emitted."""
    org_uuid = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    policy_uuid = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    exec_token = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
    api_path = f"/policy-history/policies/{policy_uuid}/{exec_token}"
    payload = {
        "metadata": {"current_page": 0, "total_pages": 1, "total_count": 2, "limit": 25},
        "data": [
            {"device_id": 1, "result_status": "success"},
            {"device_id": 2, "result_status": "failed"},
        ],
    }
    stub = StubClient(get_responses={api_path: [payload]})

    result = await describe_policy_run_result(
        cast(AutomoxClient, stub),
        org_uuid=org_uuid,
        policy_uuid=policy_uuid,
        exec_token=exec_token,
        page=0,
        limit=25,
    )

    assert result["metadata"]["pagination"].get("has_more") is False
    assert "suggested_next_call" not in result["metadata"]
