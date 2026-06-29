"""Pagination-honesty tests for the policy history, windows, and preview tools.

These wrappers previously reported a per-page list length under a field named
like a grand total, or truncated a list with no signal that more data exists.
The cases here pin the corrected contract: the per-page count and the grand
total are distinct fields, and a truncated/paged response carries an explicit
``has_more`` plus a ``suggested_next_call`` continuation.
"""

from typing import Any, cast

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.policy_crud import preview_policy_device_filters
from automox_mcp.workflows.policy_history import (
    get_policy_history_detail,
    list_policy_runs_v2,
)
from automox_mcp.workflows.policy_windows import search_policy_windows

_ORG_UUID = "11111111-2222-3333-4444-555555555555"


def _run(policy_uuid: str, run_time: str) -> dict[str, Any]:
    """A minimal policy-run record with the fields the projection keeps."""
    return {
        "policy_uuid": policy_uuid,
        "policy_name": "Patch All",
        "policy_type": "patch",
        "run_time": run_time,
        "success": 5,
    }


def _make_client(**kwargs: Any) -> StubClient:
    client = StubClient(**kwargs)
    client.org_uuid = _ORG_UUID
    return client


# ---------------------------------------------------------------------------
# list_policy_runs_v2 — filtered path: total_runs is the grand total, not the
# per-page length.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runs_v2_filtered_total_is_grand_total_not_page_len() -> None:
    # 30 runs all match the policy_type filter; one page of 10 is returned.
    pool = [_run("pol-001", f"2026-03-01T00:{i:02d}:00Z") for i in range(30)]
    client = _make_client(get_responses={"/policy-history/policy-runs": [pool]})

    result = await list_policy_runs_v2(
        cast(AutomoxClient, client),
        org_id=42,
        policy_type="patch",
        page=0,
        limit=10,
    )

    data = result["data"]
    # The page carries 10 runs, but the filtered grand total is 30.
    assert data["runs_returned"] == 10
    assert len(data["runs"]) == 10
    assert data["total_runs"] == 30
    # total_runs must not collapse to the per-page length.
    assert data["total_runs"] != data["runs_returned"]

    pagination = result["metadata"]["pagination"]
    assert pagination["has_more"] is True
    assert pagination["total_elements"] == 30
    # A continuation call is offered for the next page.
    suggested = result["metadata"]["suggested_next_call"]
    assert suggested["args"]["page"] == 1
    assert suggested["args"]["limit"] == 10


@pytest.mark.asyncio
async def test_runs_v2_filtered_last_page_has_no_continuation() -> None:
    pool = [_run("pol-001", f"2026-03-01T00:{i:02d}:00Z") for i in range(12)]
    client = _make_client(get_responses={"/policy-history/policy-runs": [pool]})

    result = await list_policy_runs_v2(
        cast(AutomoxClient, client),
        org_id=42,
        policy_type="patch",
        page=1,
        limit=10,
    )

    data = result["data"]
    # Page 1 holds the trailing 2 of 12; the total still reports the full set.
    assert data["runs_returned"] == 2
    assert data["total_runs"] == 12
    assert result["metadata"]["pagination"]["has_more"] is False
    assert "suggested_next_call" not in result["metadata"]


# ---------------------------------------------------------------------------
# policy_history_detail — slice vs. available, with a truncation signal.
# ---------------------------------------------------------------------------


def _detail_client(run_count: int) -> StubClient:
    runs = [_run("pol-001", f"2026-03-01T00:{i:02d}:00Z") for i in range(run_count)]
    return _make_client(
        get_responses={
            "/policy-history/policies/pol-001": [{"uuid": "pol-001", "name": "Patch All"}],
            "/policy-history/policy-runs/pol-001": [{"data": {"runs": runs}}],
        }
    )


@pytest.mark.asyncio
async def test_history_detail_reports_slice_vs_available_and_truncation() -> None:
    client = _detail_client(run_count=40)

    result = await get_policy_history_detail(
        cast(AutomoxClient, client),
        org_id=42,
        policy_uuid="pol-001",
        recent_runs_limit=10,
    )

    data = result["data"]
    assert data["recent_runs_count"] == 10
    assert len(data["recent_runs"]) == 10
    assert data["total_runs_available"] == 40
    # The slice count must not be reported as the available total.
    assert data["recent_runs_count"] != data["total_runs_available"]

    meta = result["metadata"]
    assert meta["recent_runs_truncated"] is True
    suggested = meta["suggested_next_call"]
    assert suggested["tool"] == "policy_history_detail"
    assert suggested["args"]["recent_runs_limit"] == 40


@pytest.mark.asyncio
async def test_history_detail_no_truncation_signal_when_full_set_fits() -> None:
    client = _detail_client(run_count=3)

    result = await get_policy_history_detail(
        cast(AutomoxClient, client),
        org_id=42,
        policy_uuid="pol-001",
        recent_runs_limit=25,
    )

    data = result["data"]
    assert data["recent_runs_count"] == 3
    assert data["total_runs_available"] == 3
    assert "recent_runs_truncated" not in result["metadata"]
    assert "suggested_next_call" not in result["metadata"]


@pytest.mark.asyncio
async def test_history_detail_limit_zero_omits_all_runs() -> None:
    client = _detail_client(run_count=5)

    result = await get_policy_history_detail(
        cast(AutomoxClient, client),
        org_id=42,
        policy_uuid="pol-001",
        recent_runs_limit=0,
    )

    data = result["data"]
    # "Set 0 to omit" — the slice is empty, not the full list.
    assert data["recent_runs"] == []
    assert data["recent_runs_count"] == 0
    # The full set is still reported as available, and the omission is signalled.
    assert data["total_runs_available"] == 5
    assert result["metadata"]["recent_runs_truncated"] is True


# ---------------------------------------------------------------------------
# search_policy_windows — default call derives has_more + suggested_next_call.
# ---------------------------------------------------------------------------


def _window(name: str) -> dict[str, Any]:
    return {"window_uuid": f"win-{name}", "window_name": name, "window_type": "exclude"}


@pytest.mark.asyncio
async def test_search_windows_default_call_emits_has_more_and_continuation() -> None:
    # Default call (page/size unset): first page of 5 with a grand total of 12.
    page_one = [_window(f"w{i}") for i in range(5)]
    client = StubClient(
        post_responses={
            f"/policy-windows/org/{_ORG_UUID}/search": [
                {"content": page_one, "total_elements": 12},
            ],
        }
    )

    result = await search_policy_windows(cast(AutomoxClient, client), org_uuid=_ORG_UUID)

    data = result["data"]
    assert data["windows_returned"] == 5
    assert data["total_elements"] == 12

    pagination = result["metadata"]["pagination"]
    assert pagination["has_more"] is True
    suggested = result["metadata"]["suggested_next_call"]
    assert suggested["tool"] == "search_policy_windows"
    assert suggested["args"]["page"] == 1
    assert suggested["args"]["size"] == 5


@pytest.mark.asyncio
async def test_search_windows_full_result_set_has_no_continuation() -> None:
    windows = [_window(f"w{i}") for i in range(3)]
    client = StubClient(
        post_responses={
            f"/policy-windows/org/{_ORG_UUID}/search": [
                {"content": windows, "total_elements": 3},
            ],
        }
    )

    result = await search_policy_windows(cast(AutomoxClient, client), org_uuid=_ORG_UUID)

    assert result["data"]["windows_returned"] == 3
    assert result["metadata"]["pagination"]["has_more"] is False
    assert "suggested_next_call" not in result["metadata"]


# ---------------------------------------------------------------------------
# preview_policy_device_filters — emit pagination when a limit is applied.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preview_emits_pagination_when_limited() -> None:
    devices = [{"id": i} for i in range(10)]
    client = StubClient(
        post_responses={
            "/policies/device-filters-preview": [{"results": devices, "size": 25}],
        }
    )

    result = await preview_policy_device_filters(
        cast(AutomoxClient, client),
        org_id=42,
        server_groups=[10],
        page=0,
        limit=10,
    )

    data = result["data"]
    assert data["devices_returned"] == 10
    # `total_devices` carries the envelope size (the grand total), not the page.
    assert data["total_devices"] == 25

    pagination = result["metadata"]["pagination"]
    assert pagination["has_more"] is True
    assert pagination["total_elements"] == 25
    suggested = result["metadata"]["suggested_next_call"]
    assert suggested["args"]["page"] == 1
    assert suggested["args"]["limit"] == 10


@pytest.mark.asyncio
async def test_preview_without_limit_has_no_pagination() -> None:
    devices = [{"id": i} for i in range(4)]
    client = StubClient(
        post_responses={
            "/policies/device-filters-preview": [{"results": devices, "size": 4}],
        }
    )

    result = await preview_policy_device_filters(
        cast(AutomoxClient, client),
        org_id=42,
        server_groups=[10],
    )

    # No limit applied: no pagination block, no per-page relabel.
    assert result["data"]["total_devices"] == 4
    assert "pagination" not in result["metadata"]
    assert "suggested_next_call" not in result["metadata"]
    assert "devices_returned" not in result["data"]
