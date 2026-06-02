"""Tests for package workflows."""

from typing import Any, cast

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxAPIError, AutomoxClient
from automox_mcp.workflows.packages import (
    list_device_packages,
    search_org_packages,
)

_DEVICE_PACKAGES: list[dict[str, Any]] = [
    {
        "id": 1,
        "display_name": "Google Chrome",
        "version": "120.0.6099",
        "installed": True,
        "repo": "Google",
        "severity": "high",
        "status": "installed",
        "is_managed": True,
    },
    {
        "id": 2,
        "name": "curl",  # uses name instead of display_name
        "version": "8.0.1",
        "installed": True,
        "repo": "homebrew",
        "patch_status": "available",  # uses patch_status instead of status
    },
    {
        "id": 3,
        "display_name": "Firefox",
        "version": "121.0",
        "installed": False,
        "repo": "Mozilla",
    },
]

_ORG_PACKAGES: list[dict[str, Any]] = [
    {
        "id": 100,
        "display_name": "Chrome",
        "version": "120.0",
        "severity": "high",
        "device_count": 42,
        "is_managed": True,
        "awaiting": False,
    },
    {
        "id": 101,
        "name": "openssl",  # uses name instead of display_name
        "version": "3.1.4",
        "severity": "critical",
        "device_count": 100,
        "is_managed": True,
        "awaiting": True,
    },
]


# ---------------------------------------------------------------------------
# list_device_packages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_packages_returns_summaries() -> None:
    client = StubClient(get_responses={"/servers/101/packages": [_DEVICE_PACKAGES]})
    result = await list_device_packages(cast(AutomoxClient, client), org_id=555, device_id=101)

    assert result["data"]["device_id"] == 101
    assert result["data"]["total_packages"] == 3
    assert len(result["data"]["packages"]) == 3


@pytest.mark.asyncio
async def test_list_packages_prefers_display_name() -> None:
    client = StubClient(get_responses={"/servers/101/packages": [_DEVICE_PACKAGES]})
    result = await list_device_packages(cast(AutomoxClient, client), org_id=555, device_id=101)

    names = [p["name"] for p in result["data"]["packages"]]
    assert "Google Chrome" in names
    assert "curl" in names  # falls back to name field


@pytest.mark.asyncio
async def test_list_packages_includes_optional_fields() -> None:
    client = StubClient(get_responses={"/servers/101/packages": [_DEVICE_PACKAGES]})
    result = await list_device_packages(cast(AutomoxClient, client), org_id=555, device_id=101)

    chrome = next(p for p in result["data"]["packages"] if p["name"] == "Google Chrome")
    assert chrome["severity"] == "high"
    assert chrome["patch_status"] == "installed"
    assert chrome["is_managed"] is True

    curl = next(p for p in result["data"]["packages"] if p["name"] == "curl")
    assert curl["patch_status"] == "available"  # from patch_status field
    assert "severity" not in curl  # no severity on this package


@pytest.mark.asyncio
async def test_list_packages_omits_absent_optional_fields() -> None:
    client = StubClient(get_responses={"/servers/101/packages": [_DEVICE_PACKAGES]})
    result = await list_device_packages(cast(AutomoxClient, client), org_id=555, device_id=101)

    firefox = next(p for p in result["data"]["packages"] if p["name"] == "Firefox")
    assert "severity" not in firefox
    assert "patch_status" not in firefox
    assert "is_managed" not in firefox


@pytest.mark.asyncio
async def test_list_packages_passes_pagination() -> None:
    client = StubClient(get_responses={"/servers/101/packages": [[]]})
    await list_device_packages(
        cast(AutomoxClient, client),
        org_id=555,
        device_id=101,
        page=2,
        limit=50,
    )

    params = client.calls[0][2]
    assert params["page"] == 2
    assert params["limit"] == 50
    assert params["o"] == 555


@pytest.mark.asyncio
async def test_list_packages_auto_paginates_until_short_page() -> None:
    """Default (no page) walks every page so 'is X installed?' is not truncated."""
    page0 = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]  # full page (size 2)
    page1 = [{"id": 3, "name": "nginx"}]  # short page → end of data
    client = StubClient(get_responses={"/servers/101/packages": [page0, page1]})
    result = await list_device_packages(
        cast(AutomoxClient, client), org_id=555, device_id=101, limit=2
    )

    assert result["data"]["total_packages"] == 3
    names = [p["name"] for p in result["data"]["packages"]]
    assert "nginx" in names  # the package on the second page is not lost
    assert result["metadata"]["complete"] is True


@pytest.mark.asyncio
async def test_list_packages_explicit_page_signals_more() -> None:
    """A full explicit page flags has_more — the endpoint gives no total."""
    full_page = [{"id": i} for i in range(50)]
    client = StubClient(get_responses={"/servers/101/packages": [full_page]})
    result = await list_device_packages(
        cast(AutomoxClient, client), org_id=555, device_id=101, page=0, limit=50
    )

    assert result["data"]["total_packages"] == 50
    assert result["metadata"]["pagination"] == {"page": 0, "page_size": 50, "has_more": True}


@pytest.mark.asyncio
async def test_list_packages_handles_non_list_response() -> None:
    client = StubClient(get_responses={"/servers/101/packages": ["unexpected"]})
    result = await list_device_packages(cast(AutomoxClient, client), org_id=555, device_id=101)
    assert result["data"]["total_packages"] == 0
    assert result["data"]["packages"] == []


# ---------------------------------------------------------------------------
# search_org_packages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_org_packages_returns_summaries() -> None:
    client = StubClient(get_responses={"/orgs/555/packages": [_ORG_PACKAGES]})
    result = await search_org_packages(cast(AutomoxClient, client), org_id=555)

    assert result["data"]["total_packages"] == 2
    names = [p["name"] for p in result["data"]["packages"]]
    assert "Chrome" in names
    assert "openssl" in names


@pytest.mark.asyncio
async def test_search_org_packages_includes_optional_fields() -> None:
    client = StubClient(get_responses={"/orgs/555/packages": [_ORG_PACKAGES]})
    result = await search_org_packages(cast(AutomoxClient, client), org_id=555)

    chrome = next(p for p in result["data"]["packages"] if p["name"] == "Chrome")
    assert chrome["device_count"] == 42
    assert chrome["is_managed"] is True
    assert chrome["awaiting"] is False


@pytest.mark.asyncio
async def test_search_org_packages_passes_filters() -> None:
    client = StubClient(get_responses={"/orgs/555/packages": [[]]})
    await search_org_packages(
        cast(AutomoxClient, client),
        org_id=555,
        include_unmanaged=True,
        awaiting=True,
        page=1,
        limit=25,
    )

    params = client.calls[0][2]
    assert params["includeUnmanaged"] == 1
    assert params["awaiting"] == 1
    assert params["page"] == 1
    assert params["limit"] == 25


@pytest.mark.asyncio
async def test_search_org_packages_false_filters_send_zero() -> None:
    client = StubClient(get_responses={"/orgs/555/packages": [[]]})
    await search_org_packages(
        cast(AutomoxClient, client),
        org_id=555,
        include_unmanaged=False,
        awaiting=False,
    )

    params = client.calls[0][2]
    assert params["includeUnmanaged"] == 0
    assert params["awaiting"] == 0


@pytest.mark.asyncio
async def test_search_org_packages_omits_none_filters() -> None:
    client = StubClient(get_responses={"/orgs/555/packages": [[]]})
    await search_org_packages(cast(AutomoxClient, client), org_id=555)

    params = client.calls[0][2]
    assert "includeUnmanaged" not in params
    assert "awaiting" not in params


# ---------------------------------------------------------------------------
# Error path tests — API errors propagate through the workflow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_device_packages_api_error_propagates() -> None:
    client = StubClient()

    async def _raise(*a: Any, **kw: Any) -> Any:
        raise AutomoxAPIError("internal error", status_code=500)

    client.get = _raise  # type: ignore[assignment]
    with pytest.raises(AutomoxAPIError, match="internal error"):
        await list_device_packages(cast(AutomoxClient, client), org_id=1, device_id=42)


@pytest.mark.asyncio
async def test_search_org_packages_api_error_propagates() -> None:
    client = StubClient()

    async def _raise(*a: Any, **kw: Any) -> Any:
        raise AutomoxAPIError("rate limited", status_code=429)

    client.get = _raise  # type: ignore[assignment]
    with pytest.raises(AutomoxAPIError, match="rate limited"):
        await search_org_packages(cast(AutomoxClient, client), org_id=1)
