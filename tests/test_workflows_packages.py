"""Tests for package workflows."""

from typing import Any, cast

import pytest
from conftest import StubClient

from automox_mcp.client import AutomoxAPIError, AutomoxClient
from automox_mcp.workflows.packages import (
    _MAX_PACKAGE_PAGES,
    list_device_packages,
    search_org_packages,
)

# Fixtures below are built from the live `Packages` DTO key set captured by a
# sanitized read-only probe of both `/servers/{id}/packages` and
# `/orgs/{id}/packages` on 2026-06-05. The live responses do NOT contain
# `status`, `patch_status`, `awaiting`, or `device_count` (verified across 800+
# org packages and the device inventory). Names/IDs are scrubbed to generic
# placeholders. Severity values use the live distribution: high, no_known_cves,
# and JSON null (None) for the device fixture; critical/high/medium added for
# the org fixture.
_DEVICE_PACKAGES: list[dict[str, Any]] = [
    {
        "id": 1,
        "display_name": "Example App",
        "version": "120.0.6099",
        "installed": True,
        "repo": "vendor",
        "severity": "high",
        "is_managed": True,
        "organization_id": 0,
        "server_id": 0,
        "package_id": 11,
        "package_version_id": 111,
        "software_id": 1111,
        "agent_severity": None,
        "cve_score": None,
        "cves": None,
        "kev_cves": None,
        "epss_score": None,
        "impact": None,
        "ignored": False,
        "group_ignored": False,
        "is_uninstallable": True,
        "requires_reboot": False,
        "patch_scope": "all",
        "patch_classification_category_id": None,
        "os_name": "Windows",
        "os_version": "10",
        "os_version_id": 1,
        "create_time": "2026-01-01T00:00:00Z",
        "deferred_until": None,
        "group_deferred_until": None,
        "secondary_id": None,
    },
    {
        "id": 2,
        "name": "example-cli",  # uses name instead of display_name
        "version": "8.0.1",
        "installed": True,
        "repo": "vendor",
        "severity": "no_known_cves",
        "is_managed": True,
        "organization_id": 0,
        "server_id": 0,
    },
    {
        "id": 3,
        "display_name": "Example Browser",
        "version": "121.0",
        "installed": False,
        "repo": "vendor",
        "severity": None,  # JSON null severity is a real, common live value
        "organization_id": 0,
        "server_id": 0,
    },
]

_ORG_PACKAGES: list[dict[str, Any]] = [
    {
        "id": 100,
        "display_name": "Example App",
        "version": "120.0",
        "severity": "high",
        "is_managed": True,
        "installed": True,
        "organization_id": 0,
        "server_id": 0,
    },
    {
        "id": 101,
        "name": "example-lib",  # uses name instead of display_name
        "version": "3.1.4",
        "severity": "critical",
        "is_managed": True,
        "installed": False,
        "organization_id": 0,
        "server_id": 0,
    },
    {
        "id": 102,
        "display_name": "Example Tool",
        "version": "2.0",
        "severity": None,  # JSON null severity
        "is_managed": True,
        "installed": True,
        "organization_id": 0,
        "server_id": 0,
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
    assert "Example App" in names
    assert "example-cli" in names  # falls back to name field


@pytest.mark.asyncio
async def test_list_packages_includes_optional_fields() -> None:
    client = StubClient(get_responses={"/servers/101/packages": [_DEVICE_PACKAGES]})
    result = await list_device_packages(cast(AutomoxClient, client), org_id=555, device_id=101)

    app = next(p for p in result["data"]["packages"] if p["name"] == "Example App")
    assert app["severity"] == "high"
    assert app["is_managed"] is True
    assert app["installed"] is True

    cli = next(p for p in result["data"]["packages"] if p["name"] == "example-cli")
    assert cli["severity"] == "no_known_cves"

    # The phantom `patch_status` projection is gone — it is never emitted because
    # the live Packages DTO has neither `status` nor `patch_status`.
    for entry in result["data"]["packages"]:
        assert "patch_status" not in entry


@pytest.mark.asyncio
async def test_list_packages_omits_absent_optional_fields() -> None:
    client = StubClient(get_responses={"/servers/101/packages": [_DEVICE_PACKAGES]})
    result = await list_device_packages(cast(AutomoxClient, client), org_id=555, device_id=101)

    browser = next(p for p in result["data"]["packages"] if p["name"] == "Example Browser")
    # null severity is dropped from the per-package entry (the legend documents
    # that absence); is_managed absent on this package.
    assert "severity" not in browser
    assert "patch_status" not in browser
    assert "is_managed" not in browser


@pytest.mark.asyncio
async def test_list_packages_severity_field_note() -> None:
    """The severity legend is attached unconditionally and marks live vs spec values."""
    client = StubClient(get_responses={"/servers/101/packages": [_DEVICE_PACKAGES]})
    result = await list_device_packages(cast(AutomoxClient, client), org_id=555, device_id=101)

    note = result["metadata"]["field_notes"]["severity"]
    assert "no_known_cves" in note["observed_live"]
    assert any("null" in v for v in note["observed_live"])
    for spec_only in ("low", "none", "unknown"):
        assert spec_only in note["spec_only_unverified"]

    # A no_known_cves package and a null-severity package both round-trip with
    # raw severity preserved (no rewriting).
    cli = next(p for p in result["data"]["packages"] if p["name"] == "example-cli")
    assert cli["severity"] == "no_known_cves"
    browser = next(p for p in result["data"]["packages"] if p["name"] == "Example Browser")
    assert "severity" not in browser  # raw None not coerced to a label


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
async def test_list_packages_auto_paginate_hits_safety_cap() -> None:
    """A host with more pages than the cap stops at _MAX_PACKAGE_PAGES and flags incomplete.

    With page_size 2 and every page full, pagination never sees a short page,
    so it walks exactly _MAX_PACKAGE_PAGES pages and reports complete=False —
    the signal that the result is truncated, not exhaustive.
    """
    # One full page (size 2) per cap slot — never a short page to end early.
    full_pages = [
        [{"id": 2 * n, "name": f"pkg{2 * n}"}, {"id": 2 * n + 1, "name": f"pkg{2 * n + 1}"}]
        for n in range(_MAX_PACKAGE_PAGES)
    ]
    client = StubClient(get_responses={"/servers/101/packages": full_pages})
    result = await list_device_packages(
        cast(AutomoxClient, client), org_id=555, device_id=101, limit=2
    )

    assert result["data"]["total_packages"] == _MAX_PACKAGE_PAGES * 2
    assert result["metadata"]["complete"] is False
    # The cap bounds the loop: exactly _MAX_PACKAGE_PAGES fetches, no over-run.
    assert len(client.calls) == _MAX_PACKAGE_PAGES


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

    assert result["data"]["total_packages"] == 3
    names = [p["name"] for p in result["data"]["packages"]]
    assert "Example App" in names
    assert "example-lib" in names


@pytest.mark.asyncio
async def test_search_org_packages_includes_optional_fields() -> None:
    client = StubClient(get_responses={"/orgs/555/packages": [_ORG_PACKAGES]})
    result = await search_org_packages(cast(AutomoxClient, client), org_id=555)

    app = next(p for p in result["data"]["packages"] if p["name"] == "Example App")
    assert app["is_managed"] is True
    assert app["severity"] == "high"

    # The phantom `awaiting` output projection is gone (the awaiting INPUT
    # filter is exercised separately and remains correct). `device_count` is
    # also absent from the live Packages DTO and is no longer projected.
    for entry in result["data"]["packages"]:
        assert "awaiting" not in entry
        assert "device_count" not in entry


@pytest.mark.asyncio
async def test_search_org_packages_severity_field_note() -> None:
    """Org search attaches the same severity legend as the device tool (shared constant)."""
    from automox_mcp.workflows.packages import _SEVERITY_FIELD_NOTE

    client = StubClient(get_responses={"/orgs/555/packages": [_ORG_PACKAGES]})
    result = await search_org_packages(cast(AutomoxClient, client), org_id=555)

    note = result["metadata"]["field_notes"]["severity"]
    assert note is _SEVERITY_FIELD_NOTE
    assert "no_known_cves" in note["observed_live"]
    for spec_only in ("low", "none", "unknown"):
        assert spec_only in note["spec_only_unverified"]


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
