"""Regression tests for honest package pagination.

These pin the input→output contract of the fixed package-pagination paths:

- ``list_device_packages`` auto-paginate: a small ``limit`` is a post-walk cap,
  not the walk page size, so the "complete" set never silently truncates at
  ``MAX_PAGES * limit``. When the walk hits its ceiling, the truncation is
  surfaced via ``metadata.pagination.has_more`` + ``metadata.suggested_next_call``.
- ``list_device_packages`` explicit page: reports a page-scoped
  ``packages_returned`` and emits ``suggested_next_call`` on a full page.
- ``search_org_packages`` default path (``limit=None``): a complete short page
  reports ``has_more=false`` instead of the old always-true tautology.
- ``get_device_full_profile``: surfaces an incomplete underlying package walk
  rather than presenting the capped total as authoritative.
"""

import copy
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxClient
from automox_mcp.workflows.compound import get_device_full_profile
from automox_mcp.workflows.packages import (
    _DEFAULT_PACKAGE_PAGE_SIZE,
    _MAX_PACKAGE_PAGES,
    list_device_packages,
    search_org_packages,
)

# ---------------------------------------------------------------------------
# list_device_packages — auto-paginate no longer silently truncates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_small_limit_does_not_shrink_walk_page_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A small `limit` caps what is RETURNED but not what is WALKED.

    Before the fix, `limit=1` clamped the walk page size to 1, so a device with
    more than ``MAX_PAGES`` packages was capped at ``MAX_PAGES * 1`` and the
    extra packages vanished. Now the walk runs at the full default page size and
    `limit` only trims the returned list — so completeness is assessed on the
    whole inventory, not on ``limit``-sized slivers.
    """
    monkeypatch.setattr("automox_mcp.workflows.packages._DEFAULT_PACKAGE_PAGE_SIZE", 2)
    # Two full default-size pages then a short page → 5 packages total.
    page0 = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
    page1 = [{"id": 3, "name": "c"}, {"id": 4, "name": "d"}]
    page2 = [{"id": 5, "name": "nginx"}]
    client = StubClient(get_responses={"/servers/101/packages": [page0, page1, page2]})

    result = await list_device_packages(
        cast(AutomoxClient, client), org_id=555, device_id=101, limit=1
    )

    # Only one package is RETURNED (the post-walk cap)...
    assert result["data"]["total_packages"] == 1
    assert len(result["data"]["packages"]) == 1
    # ...but the walk saw the whole short-terminated inventory, so it is complete
    # and there is no false has_more / suggested_next_call.
    assert result["metadata"]["complete"] is True
    assert "suggested_next_call" not in result["metadata"]
    # The walk paged at the default size, never at limit=1: every fetch sent
    # `limit=2` (the shrunk default), proving limit didn't drive the page size.
    assert all(call[2]["limit"] == 2 for call in client.calls)


@pytest.mark.asyncio
async def test_small_limit_walk_ceiling_surfaces_has_more(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the walk hits its ceiling, a small `limit` no longer hides it.

    The old behavior returned a quietly-truncated set with only
    ``metadata.complete=False`` as a signal. Now the ceiling surfaces as
    ``has_more=true`` plus a concrete ``suggested_next_call``.
    """
    monkeypatch.setattr("automox_mcp.workflows.packages._DEFAULT_PACKAGE_PAGE_SIZE", 2)
    full_pages = [
        [{"id": 2 * n, "name": f"pkg{2 * n}"}, {"id": 2 * n + 1, "name": f"pkg{2 * n + 1}"}]
        for n in range(_MAX_PACKAGE_PAGES)
    ]
    client = StubClient(get_responses={"/servers/101/packages": full_pages})

    result = await list_device_packages(
        cast(AutomoxClient, client), org_id=555, device_id=101, limit=10
    )

    metadata = result["metadata"]
    assert metadata["complete"] is False
    assert metadata["pagination"]["has_more"] is True
    assert metadata["pagination"]["next_page"] == _MAX_PACKAGE_PAGES
    assert metadata["suggested_next_call"] == {
        "tool": "list_device_packages",
        "args": {"device_id": 101, "page": _MAX_PACKAGE_PAGES, "limit": 10},
    }
    # The returned list is capped at the post-walk limit, not the walk total.
    assert len(result["data"]["packages"]) == 10


# ---------------------------------------------------------------------------
# list_device_packages — explicit page uses packages_returned + suggested_next_call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_explicit_full_page_uses_packages_returned_and_suggests_next() -> None:
    full_page = [{"id": i} for i in range(50)]
    client = StubClient(get_responses={"/servers/101/packages": [full_page]})

    result = await list_device_packages(
        cast(AutomoxClient, client), org_id=555, device_id=101, page=3, limit=50
    )

    # Page-scoped name, not the exhaustive `total_packages` key.
    assert result["data"]["packages_returned"] == 50
    assert "total_packages" not in result["data"]
    assert result["metadata"]["pagination"]["has_more"] is True
    assert result["metadata"]["suggested_next_call"] == {
        "tool": "list_device_packages",
        "args": {"device_id": 101, "page": 4, "limit": 50},
    }


@pytest.mark.asyncio
async def test_explicit_short_page_no_suggestion() -> None:
    short_page = [{"id": i} for i in range(2)]
    client = StubClient(get_responses={"/servers/101/packages": [short_page]})

    result = await list_device_packages(
        cast(AutomoxClient, client), org_id=555, device_id=101, page=0, limit=50
    )

    assert result["data"]["packages_returned"] == 2
    assert result["metadata"]["pagination"]["has_more"] is False
    assert "suggested_next_call" not in result["metadata"]


# ---------------------------------------------------------------------------
# search_org_packages — default short page is complete (no tautology)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_org_default_short_page_has_more_false() -> None:
    """`limit=None` + a page shorter than the upstream default ⇒ has_more False.

    The old default-path test was a tautology (`page_count >= page_count`), so a
    complete short page always claimed more pages existed. Now the comparison is
    against the real upstream default page size.
    """
    short_page = [
        {"id": i, "display_name": f"pkg{i}", "version": "1.0", "severity": None} for i in range(3)
    ]
    client = StubClient(get_responses={"/orgs/555/packages": [short_page]})

    result = await search_org_packages(cast(AutomoxClient, client), org_id=555)

    assert result["data"]["returned_package_count"] == 3
    assert result["metadata"]["pagination"]["has_more"] is False
    # The reported page size is the upstream default, not the (misleading) count.
    assert result["metadata"]["pagination"]["page_size"] == _DEFAULT_PACKAGE_PAGE_SIZE


@pytest.mark.asyncio
async def test_search_org_default_full_page_has_more_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A default-path page that fills the upstream default size still flags more."""
    monkeypatch.setattr("automox_mcp.workflows.packages._DEFAULT_PACKAGE_PAGE_SIZE", 5)
    full_page = [
        {"id": i, "display_name": f"pkg{i}", "version": "1.0", "severity": None} for i in range(5)
    ]
    client = StubClient(get_responses={"/orgs/555/packages": [full_page]})

    result = await search_org_packages(cast(AutomoxClient, client), org_id=555)

    assert result["data"]["returned_package_count"] == 5
    assert result["metadata"]["pagination"]["has_more"] is True


# ---------------------------------------------------------------------------
# get_device_full_profile — surfaces an incomplete package walk
# ---------------------------------------------------------------------------


def _patch_full_profile_packages(
    monkeypatch: pytest.MonkeyPatch, packages_result: dict[str, Any]
) -> None:
    """Patch the three sub-workflows so only the packages result varies."""
    fn_globals = get_device_full_profile.__globals__
    devices_mod = fn_globals["devices"]
    packages_mod = fn_globals["packages"]
    monkeypatch.setattr(
        devices_mod, "describe_device", AsyncMock(return_value={"data": {}, "metadata": {}})
    )
    monkeypatch.setattr(
        devices_mod, "get_device_inventory", AsyncMock(return_value={"data": {}, "metadata": {}})
    )
    monkeypatch.setattr(
        packages_mod,
        "list_device_packages",
        AsyncMock(return_value=copy.deepcopy(packages_result)),
    )


@pytest.mark.asyncio
async def test_full_profile_surfaces_incomplete_package_walk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An incomplete underlying walk is flagged, not presented as authoritative."""
    incomplete = {
        "data": {
            "device_id": 101,
            "total_packages": 50,
            "packages": [{"id": i, "name": f"pkg-{i}", "version": "1.0"} for i in range(50)],
        },
        "metadata": {"complete": False},
    }
    _patch_full_profile_packages(monkeypatch, incomplete)
    client = StubClient()

    result = await get_device_full_profile(
        cast(AutomoxClient, client), org_id=555, device_id=101, detail_limit=5
    )

    pkg_section = result["data"]["packages"]
    assert pkg_section["total_is_complete"] is False
    # The note must say the total is a floor ("at least"), never present it as exact.
    assert "at least" in pkg_section["note"]
    assert "list_device_packages" in pkg_section["note"]


@pytest.mark.asyncio
async def test_full_profile_complete_walk_reports_authoritative_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A complete walk keeps the exact-total semantics (no false 'at least')."""
    complete = {
        "data": {
            "device_id": 101,
            "total_packages": 3,
            "packages": [{"id": i, "name": f"pkg-{i}", "version": "1.0"} for i in range(3)],
        },
        "metadata": {"complete": True},
    }
    _patch_full_profile_packages(monkeypatch, complete)
    client = StubClient()

    result = await get_device_full_profile(
        cast(AutomoxClient, client), org_id=555, device_id=101, detail_limit=25
    )

    pkg_section = result["data"]["packages"]
    assert pkg_section["total_is_complete"] is True
    assert pkg_section["truncated"] is False
    assert pkg_section["note"] is None
