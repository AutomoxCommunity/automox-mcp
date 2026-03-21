"""Tests for discover_capabilities meta-tool."""

from __future__ import annotations

from typing import Any

import pytest

from automox_mcp.tools.meta_tools import _DOMAIN_CATALOG, register


class StubServer:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self, name: str, description: str = "", **kwargs):
        def decorator(func):
            self.tools[name] = func
            return func
        return decorator


class FakeClient:
    org_id = 42
    org_uuid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    account_uuid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


@pytest.fixture
def server():
    s = StubServer()
    register(s, read_only=False, client=FakeClient())
    return s


@pytest.mark.asyncio
async def test_discover_capabilities_valid_domain(server):
    result = await server.tools["discover_capabilities"](domain="devices")
    data = result["data"]
    assert data["domain"] == "devices"
    assert data["tool_count"] > 0
    assert isinstance(data["tools"], list)
    assert data["tools"][0]["name"] == "list_devices"


@pytest.mark.asyncio
async def test_discover_capabilities_unknown_domain(server):
    result = await server.tools["discover_capabilities"](
        domain="nonexistent"
    )
    data = result["data"]
    assert "error" in data
    assert "available_domains" in data


@pytest.mark.asyncio
async def test_discover_capabilities_no_domain_lists_all(server):
    result = await server.tools["discover_capabilities"]()
    data = result["data"]
    assert "available_domains" in data
    assert "devices" in data["available_domains"]
    assert "policies" in data["available_domains"]


@pytest.mark.asyncio
async def test_discover_capabilities_case_insensitive(server):
    result = await server.tools["discover_capabilities"](domain="DEVICES")
    assert result["data"]["domain"] == "devices"


def test_all_ten_domains_present():
    expected = {
        "devices", "policies", "patches", "groups", "events",
        "reports", "audit", "webhooks", "account", "compound",
    }
    assert set(_DOMAIN_CATALOG.keys()) == expected


def test_catalog_entries_are_tuples_of_name_and_description():
    for domain, tools in _DOMAIN_CATALOG.items():
        for entry in tools:
            assert isinstance(entry, tuple), f"Bad entry in {domain}"
            assert len(entry) == 2, f"Bad entry in {domain}: {entry}"
            name, desc = entry
            assert isinstance(name, str) and name
            assert isinstance(desc, str) and desc
